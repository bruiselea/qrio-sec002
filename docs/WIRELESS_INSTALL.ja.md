# 未改造Q-SL1への配線なし初回導入

この手順は所有するQ-SL1に対して使います。使用するのはLinux PCまたはラズパイのBluetoothです。Windows標準BLE API/Web Bluetoothだけでは独自L2CAP CIDへ送れないため、WindowsからはSSHでLinux側を操作します。

```text
Windows PC（任意） ── SSH/LAN ── Linux PC / Raspberry Pi ── Bluetooth ── Q-SL1
```

**この配布版の純正→SEC002全無線導入は実機通し試験未実施です。** 方式の無線転送実績とSEC002自体の有線導入・動作実績を区別しています。広告が止まれば有線救済が必要で、自動で純正へ戻る仕組みはありません。

## 1. 手元とホストの準備

本体はドアから外した状態で作業し、正常な電池で起動音・広告が出ることを確認します。Linux/ラズパイを本体の近くへ置き、Qrioアプリや既存ゲートウェイなど、同じ鍵へ接続する他のソフトを停止します。このプロジェクトのHomeKitゲートウェイが動いている場合だけ、次で停止します。

```sh
sudo systemctl stop qrio-sl1-home.service
```

無線導入には所有者鍵を使いませんが、これは本体の既知の保守経路が認証を要求しないためです。導入後の通常操作には正規の所有者鍵が必要です。このツールは所有者登録を行いません。

Linux側のPythonは3.11以上、BlueZと動作するBluetoothアダプタが必要です。依存導入の例はDebian/Raspberry Pi OS向けです。

```sh
sudo apt update
sudo apt install python3-venv bluez unzip
```

配布ZIPをLinuxへ転送して展開します。Windowsで受け取った場合のPowerShell例です。`YOUR_USER`と`YOUR_PI`は実際のSSH接続先に置き換えます。

```powershell
scp .\qrio-sec002-toolkit-v0.1.0.zip YOUR_USER@YOUR_PI:~/
scp .\SHA256SUMS.txt YOUR_USER@YOUR_PI:~/
ssh YOUR_USER@YOUR_PI
```

以後はLinuxの端末で実行します。

```sh
sha256sum -c SHA256SUMS.txt
unzip qrio-sec002-toolkit-v0.1.0.zip
cd qrio-sec002-toolkit-v0.1.0
bash bootstrap-linux.sh
.venv/bin/python -m unittest discover -s tests -v
```

ZIPのハッシュ一致はファイルの一致確認で、配布者の身元を証明する署名ではありません。入手元も確認してください。bootstrapは仮想環境へ依存を入れるだけで、鍵へ接続・書き込みしません。`curl | sudo`による実行は不要です。

## 2. 自分の鍵のBluetoothアドレスを選ぶ

```sh
sudo .venv/bin/python -m qsl1sec scan --seconds 10
```

表示された対象アドレスを次の`AA:BB:CC:DD:EE:FF`へ置き換えます。この表記は例です。複数台が見える場合は、距離や電池の状態を自分で管理できる個体を特定してから進めます。以後の段階は暗号化バックアップに保存したアドレスと128ビットの広告識別子へ結び付けます。

## 3. 書き込み前に全EEPROMを2回保存

```sh
sudo .venv/bin/python -m qsl1sec backup \
  --address AA:BB:CC:DD:EE:FF --output .private/original.qsb
```

12文字以上のバックアップ用パスフレーズを2回、端末で入力します。チャット、Issue、コマンド引数へ書かないでください。64KiBを2回読み、完全一致と対応するDS1を確認した後、暗号化保存・復号照合します。ここでは本体へメモリを書きません。

`original.qsb`を別の保管先へもコピーしてください。全EEPROMには所有者情報が含まれるので、暗号化されていても一般公開しません。入力したパスフレーズは前の利用者のものではなく、このバックアップのために自分で新しく決めるものです。

## 4. SEC002を予備領域へ作成・転送

```sh
sudo .venv/bin/python -m qsl1sec stage --backup .private/original.qsb
```

手元で純正DSへ差分を適用し、SEC002の固定ハッシュと一致することを確認します。その後、最新の全EEPROMも暗号化保存してからDS2へ転送します。書き込みは16バイトのページ境界を跨がない最大11バイトずつで、ページの読み戻しと全64KiBの予定値一致を確認します。純正DS1・SS1・所有者領域は書きません。

最後に一時的な書き込み保護設定を戻し、13秒の待機後に純正`1.4.01`のまま起動することを確認します。この段階ではSEC002へ切り替えません。所要時間はBluetooth環境に依存し、数分以上かかることがあります。進捗表示が続く間は電源を切らないでください。

ローカルの生成物だけを確認したい場合は、任意で次も使えます。

```sh
.venv/bin/python -m qsl1sec build \
  --backup .private/original.qsb --output .private/SEC002.qsb
```

生成物も暗号化され、元の純正コードを含むため配布ZIPへ加えません。

## 5. 最終切替

stageが正常終了し、バックアップを保管した状態で実行します。

```sh
sudo .venv/bin/python -m qsl1sec activate --backup .private/original.qsb
```

再度、純正DS1・自分のSS1・SEC002全体を照合します。SS2を元のSS1から複製してDS2を参照させ、読み戻しが一致してからSS1先頭1バイトを変更します。WP設定を戻して接続を閉じ、FWU watchdogの再起動を待ちます。

再接続して`Q-SL1 / SEC002`を取得し、ROMアドレス0の読み出し準備要求へ応答がなく、その後もGATTが応答することを調べます。消去・書き込み・コード実行の攻撃試験はしません。

**ここから先、この個体への無線ファーム更新はできません。** 本体が起動しない場合も、同じコマンドの繰り返しで救済できるとは限りません。[復旧手順](RECOVERY.ja.md)へ進みます。

## 6. 再起動後の確認

```sh
sudo .venv/bin/python -m qsl1sec verify --backup .private/original.qsb
```

一度電池を抜いて入れ直した後にも同じ確認を行います。このverifyは版表示・既知の読み出し経路の無応答・GATT生存を確認するもので、所有者認証・モーターの実回転・防犯性能全般の検査ではありません。自分の正規の操作鍵やHomeKit連携は、ドアから外した状態で別に確かめてください。

既存ゲートウェイを停止していた場合は、確認後に再開します。

```sh
sudo systemctl start qrio-sl1-home.service
```

このツールはバックアップやファームをクラウドへアップロードしません。ネットワーク利用は初回の依存取得、SSHと、実機とのBluetooth通信です。
