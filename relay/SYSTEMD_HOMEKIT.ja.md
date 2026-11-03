# systemd常駐とiPhoneのホーム

対象はLinux/Pi OSとsystemdの暗号化credentialを使う構成です。既存のHome Assistantと認証付きMQTT brokerがPi上で動いており、[単独の中継状態取得](README.ja.md)が成功した状態から進めます。所有者登録・MQTT broker・Home Assistant本体のインストーラーは含みません。

## 実行用ファイルと環境

ソースをroot所有で配置し、秘密情報はソースへ混ぜません。次は新しい`/opt/qrio-relay`へ導入する例です。すでに同名の配置がある場合は、そのバックアップを取ってから更新します。

```sh
sudo install -d -m 755 /opt/qrio-relay
sudo install -m 644 relay/qrio_protocol.py relay/qrio_live.py relay/qrio_esphome_transport.py relay/qrio_home_daemon.py relay/bluez_qrio_agent.py relay/requirements-runtime.txt /opt/qrio-relay/
sudo python3 -m venv /opt/qrio-relay/.venv
sudo /opt/qrio-relay/.venv/bin/python -m pip install -r /opt/qrio-relay/requirements-runtime.txt
```

systemユーザー`qrio-sl1`がなければ作成します。既存ユーザーがいる場合は作り直しません。

```sh
sudo useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin qrio-sl1
```

## credentialを設定

`mqtt.example.json`を自分の保護されたディレクトリへコピーし、エディターで本人のMQTT用ユーザー名・パスワードを設定します。このサービス例はPi上の`127.0.0.1:1883`を使います。MQTTの匿名アクセスは禁止し、`qrio/sl1/#`と必要なDiscoveryトピックへの権限を本人のbrokerで設定してください。

`owner.json`、`mqtt.private.json`、`relay.private.json`をモード600で保管し、次のようにsystemd用へ暗号化します。秘密の値をコマンド引数へ書きません。

```sh
sudo install -d -m 700 /etc/credstore.encrypted
sudo systemd-creds encrypt --name=owner.json ~/.config/qrio-relay/owner.json /etc/credstore.encrypted/qrio-relay-owner.cred
sudo systemd-creds encrypt --name=mqtt.json ~/.config/qrio-relay/mqtt.private.json /etc/credstore.encrypted/qrio-relay-mqtt.cred
sudo systemd-creds encrypt --name=relay.json ~/.config/qrio-relay/relay.private.json /etc/credstore.encrypted/qrio-relay-api.cred
```

すでに同じ出力がある場合は既存の鍵を保管し、別名で更新を計画してください。`systemd-creds`が利用できないOSで、平文キーをサービスファイルに貼り付けて代用しないでください。

## サービスを設定

`qrio-relay.service.example`をローカルで編集し、末尾の`IPAddressAllow=192.168.1.123/32`を、予約したXIAOのIPへ替えます。秘密鍵はサービスファイルへ入れません。

```sh
sudo install -m 644 relay/qrio-relay.service.example /etc/systemd/system/qrio-relay.service
sudo systemctl daemon-reload
sudo systemctl enable --now qrio-relay.service
sudo systemctl status qrio-relay.service --no-pager
sudo cat /var/lib/qrio-sl1-gateway/bridge-status.json
```

例示ファイル自身を編集してからinstallしてください。`IPAddressDeny=any`は維持し、XIAOのIPとlocalhostだけを許可する構成です。別のサービスから同じ鍵を操作している場合は、その既存サービスを止めてから起動します。2つのゲートウェイを同時に動かさないでください。

## 既存ゲートウェイから切り替える場合

既存の所有者・MQTT credential、HomeKitペアリング、Home Assistantエンティティは保管したまま使います。まず新しいランタイムを別ディレクトリ・別venvへ置き、単独の`status --relay-config ...`で確認します。

その後、既存サービスを停止し、ExecStartを新しい`qrio_home_daemon.py`へ変更、`LoadCredentialEncrypted=relay.json:...`と`QRIO_RELAY_CONFIG`を追加します。credentialの実際のマウント先は**サービス名**に応じて変わるため、例を別のサービス名で使う場合は`/run/credentials/サービス名.service/relay.json`へ合わせます。XIAOのIP許可も追加します。

所有者鍵の再登録やHomeKitペアリングのリセットは行いません。切替に失敗した場合は停止して元のExecStart・追加設定へ戻し、Piを鍵の近くに置いて以前の直接BLE構成を再開します。元のサービスファイルとソースを切替前に保存してください。

## Home AssistantとiPhone

1. Home Assistantの「設定→デバイスとサービス」でMQTT統合を設定し、このゲートウェイと同じ本人のbrokerへ接続します。
2. ゲートウェイがDiscoveryを公開すると、通常は`lock.qrio_sl1`が作られます。同名エンティティがある環境では実際のIDを確認してください。
3. HomeKit Bridge統合へこの鍵だけを公開します。この構成で実証したのは`accessory`モードです。GUIで選べない詳細は[公式の手動設定](https://www.home-assistant.io/integrations/homekit/)を参照します。
4. iPhoneを同じLANへつなぎ、Home Assistantがローカルで表示する追加用QRをホームアプリで読み取ります。既存のペアリングがある場合は追加し直しません。
5. XIAOを玄関で給電し、Piを離した状態で施錠1回を自分で確認します。通信成功だけでなく、実際の施錠も確認します。

新規のHomeKit公開をYAMLで行う場合の例です。すでにGUIで同じ鍵を公開している場合は、重複した設定を追加しません。

```yaml
homekit:
  - name: Qrio Home Relay
    port: 21064
    mode: accessory
    filter:
      include_entities:
        - lock.qrio_sl1
```

HomeKitはLAN内のmDNSとHAP通信を使います。既存ファイアウォールで遮断される場合は、必要なLANからのUDP 5353と、選んだHomeKit TCPポートだけを許可します。ガード全体を解除する必要はありません。外出先からのホーム操作には、別途Appleのホームハブなどの構成が必要です。

本実装の状態表示は最後に成功したモーター動作から30秒までです。`ReadStatus`の電池・設定値から実位置を推測しません。手でつまみを回した位置の追跡は未対応です。

資料：[Home Assistant MQTT](https://www.home-assistant.io/integrations/mqtt/)、[HomeKit Bridge](https://www.home-assistant.io/integrations/homekit/)。
