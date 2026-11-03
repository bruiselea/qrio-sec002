# XIAO ESP32C3によるQ-SL1のLAN中継

Seeed Studio XIAO ESP32C3＋外付け2.4GHzアンテナを玄関に置き、ラズパイからWi-Fi／LAN経由でQ-SL1を操作します。所有者認証はラズパイが担当します。

```text
iPhone ホーム → Home Assistant / MQTT → ラズパイ
                                          ↓ 暗号化LAN
                                  XIAO ESP32C3
                                          ↓ Bluetooth
                                        Q-SL1
```

**所有する1個体で、中継経由の所有者認証・状態取得、ラズパイを離した状態でのiPhoneからの施錠とモーター完了を確認しました。** 別個体・長期運転・公開手順を用いた新規環境の一括構築は未確認です。SEC002の「純正から全無線で導入するインストーラー」の検証状況とは別です。

## 前提と同梱範囲

- XIAO ESP32C3、対応アンテナ、USBデータケーブル、玄関でのUSB給電、自宅の2.4GHz Wi-Fiを用意します。Q-SL1との配線は不要です。
- ビルド用PCはPython 3.12以上、ラズパイの実行用はPython 3.11以上を使います。
- **登録済みの所有者操作鍵`owner.json`が必要です。** この追加には新規のオーナー登録や回復vaultからの鍵取り出しは含みません。カード番号だけでは動かせません。
- 操作用JSONに必要な項目は`lock_uuid`、`phone_uuid`、`signing_private_pem`、`mq_public`、`challenge_a`、`challenge_b`です。自分の本体へ登録済みの鍵を用意し、内容を公開しないでください。
- iPhoneへの公開には既存のHome Assistant・認証付きMQTT brokerが必要です。まず単独の状態取得を確認し、その後で既存HomeKitへつなぎます。

`qrio_protocol.py`に認証とフレーミングを整理しているので、この中継ランタイムには解析用モジュール、SDK、純正APKは不要です。純正ファーム、実機ダンプ、所有者鍵、Wi-Fi情報、ビルド済みイメージは同梱しません。

## 1. ソースと環境を準備

`v0.1.0`のRelease ZIPには中継コードは入っていません。リポジトリの最新ソースを取得します。

```sh
git clone https://github.com/bruiselea/qrio-sec002.git
cd qrio-sec002
```

Windowsでのビルド環境例です。ESPHome用とラズパイ実行用の環境を分けます。ESPHomeの依存するMQTTライブラリの版は、ゲートウェイ側と異なります。

```powershell
python -m venv .venv-firmware
.venv-firmware\Scripts\python -m pip install -r relay\requirements-build.txt
```

## 2. Wi-Fiと暗号鍵をローカルで作成

```powershell
.venv-firmware\Scripts\python relay\prepare.py --output "$env:USERPROFILE\.qrio-sl1\relay-xiao"
```

SSIDとWi-Fiパスワードを端末で入力します。パスワードは非表示です。32バイトのAPI鍵は自動生成します。既存の出力フォルダーは上書きしません。Linuxの場合は`python relay/prepare.py --output ~/.qrio-sl1/relay-xiao`のように指定します。

この私有フォルダーには`secrets.yaml`と設定のコピーが作られます。ビルド後のファームにもWi-Fi情報とAPI鍵が入るため、フォルダーやファームをGitHubへ追加しません。`--demo`は架空のWi-Fiでコンパイル確認するためのモードです。

## 3. XIAOをビルド・USB書き込み

電源を外したXIAOへ対応する外付けアンテナを取り付け、USBでPCにつなぎます。Q-SL1のUARTや電源端子へはつなぎません。

```powershell
.venv-firmware\Scripts\python -m serial.tools.list_ports
.venv-firmware\Scripts\python -m esptool --port COM_PORT read-mac
.venv-firmware\Scripts\python relay\build.py --config "$env:USERPROFILE\.qrio-sl1\relay-xiao\xiao-esp32c3.yaml"
.venv-firmware\Scripts\python relay\build.py --action upload --device COM_PORT --config "$env:USERPROFILE\.qrio-sl1\relay-xiao\xiao-esp32c3.yaml"
```

`COM_PORT`をXIAOの実際のポートへ置き換え、表示されたWi-Fi MACを手元に控えます。別のC3/UART変換器と混同しないでください。書き込みはXIAOへ行い、Q-SL1のファームは変更しません。XIAOに残したいプログラムがある場合は先にフラッシュを保存します。

`build.py`は子プロセスだけで他案件のIDF環境変数を除きます。Windowsではダウンロードと一時ファイルを同じボリュームへ置きます。初回はESP-IDFとコンパイラの取得に時間がかかります。アンテナ・USBの扱いは[Seeed公式](https://wiki.seeedstudio.com/XIAO_ESP32C3_WiFi_Usage/)も確認してください。

## 4. 暗号化LAN接続を確認

書き込み後、XIAOがWi-Fiにつながった状態で実行します。

```powershell
.venv-firmware\Scripts\python relay\export_gateway_config.py --build-dir "$env:USERPROFILE\.qrio-sl1\relay-xiao" --mac 00:11:22:33:44:55 --output "$env:USERPROFILE\.qrio-sl1\relay-xiao\relay.private.json"
```

MACは例です。USBで控えた**XIAOのWi-Fi MAC**に置き換えます。mDNSで見つからない場合は`--host XIAOのIPv4`を追加します。APIの暗号化認証と中継器の識別が通ると、Pi向けの秘密設定を保存します。この確認は鍵へ接続しません。

ルーターでXIAOのMACに対するDHCP予約を設定します。IPが変わると、秘密設定の`host`とsystemdの許可先を両方更新する必要があります。

## 5. ラズパイで中継をテスト

Piにもソースを取得し、専用環境を用意します。

```sh
python3 -m venv .venv-relay
.venv-relay/bin/python -m pip install -r relay/requirements-runtime.txt
.venv-relay/bin/python relay/verify.py
```

`relay.private.json`と自分の`owner.json`は、SSH/SCPで本人の私有ディレクトリへ置きます。転送先ディレクトリを先に保護しておきます。以下の`YOUR_USER@YOUR_PI`は自分の接続先に置き換えます。

```powershell
ssh YOUR_USER@YOUR_PI "install -d -m 700 .config/qrio-relay"
scp "$env:USERPROFILE\.qrio-sl1\relay-xiao\relay.private.json" YOUR_USER@YOUR_PI:.config/qrio-relay/relay.private.json
ssh YOUR_USER@YOUR_PI "chmod 600 .config/qrio-relay/relay.private.json"
```

Pi側で`owner.json`も同じように保護します。自分が安全に保管していたファイルを使い、既存の鍵は上書きしません。

```sh
chmod 600 ~/.config/qrio-relay/owner.json
.venv-relay/bin/python relay/qrio_live.py status \
  --credential ~/.config/qrio-relay/owner.json \
  --relay-config ~/.config/qrio-relay/relay.private.json --reset-pairing
```

XIAOは鍵の室内側30cm〜1m程度でUSB給電します。金属扉へアンテナを密着させず、Wi-Fiも届く位置に置きます。同じ鍵へ接続する既存ゲートウェイは、この単独診断の間は止めてください。

`authenticated: true`と`settings_fields`が返れば、所有者認証と読み取りが成功しています。`settings_fields`は実際の施解錠位置を表すものではありません。`--relay-config`を省略するとローカルBluetoothの経路になるため、中継の確認では必ず指定します。

実際に施錠を試す場合は、本体の状況を自分で確認してから`status`を`lock`に替えて1回だけ実行し、完了応答と実際の施錠を確認します。`unlock`は解錠する操作です。ツールはモーター命令を自動再送しません。

## 6. 常駐・HomeKitへの接続

詳しい手順は[SYSTEMD_HOMEKIT.ja.md](SYSTEMD_HOMEKIT.ja.md)にあります。`qrio_home_daemon.py`がMQTT Discoveryで`lock.qrio_sl1`を公開し、Home AssistantのHomeKit BridgeからiPhoneへ追加する構成です。既存のHomeKitがある場合はペアリングを作り直す必要はありません。

状態は最後の正常なモーター完了から30秒で不明へ戻します。手動つまみの追跡は未対応です。通信断時に成功と仮定せず、操作を再生しません。

## 仕組み・検証・配布

- [実装と検証範囲](TESTING.ja.md)
- [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy/)、[暗号化API](https://esphome.io/components/api/)
- 独自ソース・設定・説明は[MIT License](LICENSE)。ESPHomeやPython依存には、それぞれのライセンスが適用されます。

所有者鍵はPiへ保持し、XIAOへ転送しません。LANはランダム鍵によるNoise暗号化で、XIAOのOTA更新も同じ鍵で認証・暗号化します。API鍵を持つ端末はESPHome標準の汎用Bluetooth proxyも利用できるため、API鍵も公開しないでください。専用アダプターのGATT範囲制限は、ESPHome全体を鍵専用に制限するものではありません。
