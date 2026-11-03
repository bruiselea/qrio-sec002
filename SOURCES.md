# 参考資料・先行調査への謝辞

このプロジェクトは、先行するハードウェア解析、メーカーの公開資料、旧アプリと所有する実機の解析、オープンソースの通信基盤をもとにしています。以下に、何を参考にし、公開するコードへどう関係するかを記します。整理日：2026-11-03。

## Q-SL1の先行調査：bakueikozo氏／honeylab

- [bakueikozo/qriohack](https://github.com/bakueikozo/qriohack)：書き込み用FPCの端子表、UART接続、WICEDでの独自アプリ開発を調べる出発点として参照しました。取得して調査した版は[`c0aab09b131fe390cc376aab45d4e0512efbd8ea`](https://github.com/bakueikozo/qriohack/tree/c0aab09b131fe390cc376aab45d4e0512efbd8ea)です。
- honeylab's blog「[サービス終了するQrioLock（初代）のファームウェア書き換え＆プログラミング成功](https://honeylab.hatenablog.jp/entry/2023/06/03/090731)」（2023-06-03）：分解、回路・I/Oの調査、隠されたフラットケーブルと独自ファームの先行実績を参照しました。

端子表・分解写真・開発実績を公開した先行調査に感謝します。このリポジトリへ同氏の写真、回路図、記事本文、OBAQのソースを転載していません。本プロジェクトのSEC002差分、所有者認証、UART復旧・LAN中継コードを、同氏が実装・検証したものとする表記もしていません。

## Broadcom／Cypress／InfineonのROM・起動・更新資料

| 資料 | 参照した範囲 |
| --- | --- |
| [Infineon：BCM20732 Memory Map Architecture](https://community.infineon.com/t5/Knowledge-Base-Articles/BCM20732-Memory-Map-Architecture/ta-p/246756) | BCM20732/36/37系のROM・RAM・EEPROM、初期化後のRAM利用の背景 |
| [Infineon：How image is validated during bootup?](https://community.infineon.com/t5/Smart-Bluetooth/How-image-is-validated-during-bootup/td-p/198938) | アプリ作成関数とBLEスタックの初期化順、リセット時UART RXとプログラミングモード |
| [Infineon：20736-A1 FWU／utility API](https://infineon.github.io/btsdk-docs/BT-SDK/20736-A1_Bluetooth/API/group__utility.html) | FWUのAPI名・機能の背景。Q-SL1対象ROMと一致する保証には使っていない |

調査時には[j123m456/WICED-Smart-SDK](https://github.com/j123m456/WICED-Smart-SDK/tree/79d9f0fcdbea76140cb8f69e25067bd09ddf0e40)の固定コミット`79d9f0fcdbea76140cb8f69e25067bd09ddf0e40`も参照しました。**第三者が置いたSDKのミラーであり、メーカーの公式配布先とは区別します。**

- [`spar/common/spar_setup.c`のGCC用初期化処理](https://github.com/j123m456/WICED-Smart-SDK/blob/79d9f0fcdbea76140cb8f69e25067bd09ddf0e40/Wiced-Smart/spar/common/spar_setup.c#L132)：BSS初期化と、常駐領域末尾に32を加えて16バイト整列する境界計算。文鎮化資料の「32バイト差」を比較した具体的な参照元です。
- [`spar/gcc/spar_ram.ld`](https://github.com/j123m456/WICED-Smart-SDK/blob/79d9f0fcdbea76140cb8f69e25067bd09ddf0e40/Wiced-Smart/spar/gcc/spar_ram.ld#L100)：BSSと初期化コードの配置、後続の動的メモリ利用。
- [`bleapp/utils/bleappfwu.h`](https://github.com/j123m456/WICED-Smart-SDK/blob/79d9f0fcdbea76140cb8f69e25067bd09ddf0e40/Wiced-Smart/bleapp/utils/bleappfwu.h)、[`bleapp/lestack/l2cap/lel2cap.h`](https://github.com/j123m456/WICED-Smart-SDK/blob/79d9f0fcdbea76140cb8f69e25067bd09ddf0e40/Wiced-Smart/bleapp/lestack/l2cap/lel2cap.h)：更新処理とL2CAPの宣言・構造を照合するために参照。

SDK本体・ヘッダー・ライブラリー・ネイティブROMコードは同梱していません。資料中の一般説明を、そのまま個体の故障原因やハードウェア動作の証拠とはしていません。

## 所有者登録・MQ処理：旧Qrioアプリと実機の解析

`onboarding/`と`relay/qrio_protocol.py`の登録・認証メッセージは、旧Androidアプリのパッケージ`me.qrio.smartlock`、版1.8.7、および所有するQ-SL1の通信・取得済みデータを調べ、本プロジェクトで再実装したものです。旧APKの挙動を参照しており、クリーンルーム実装を主張していません。

解析時のAPKは第三者アーカイブ経由で入手した保管ファイルです。当時の取得経路は[APKPureの同パッケージ掲載ページ](https://apkpure.net/qrio-smart-lock/me.qrio.smartlock)で、過去の解析資料の来歴として記載しています。Qrio公式から直接取得したファイルであるとは案内しません。公開ツールは利用者がローカルに指定したファイルをデータとして読み、APKの自動取得・インストール・実行はしません。

MQ公開鍵生成の参照元は、そのAPK内`lib/x86_64/libmq.so`の`MQ_COEF`とネイティブ処理です。Pythonの演算結果は9つの合成入力で元処理のメモリー内エミュレーションと比較しました。APK・係数表・ネイティブライブラリーは同梱していません。

対応ライブラリーのハッシュはファイル照合用で、個体の所有者鍵ではありません。また、指紋の一致だけで第三者配布物の公式な真正性や再配布許諾を保証するものでもありません。[登録の条件](onboarding/README.ja.md)と[配布範囲](NOTICE.md)を参照してください。

## C3／XIAOとホーム連携

| 参照元 | 本プロジェクトでの利用 |
| --- | --- |
| [Espressif：ESP32-C3 USB Serial/JTAG](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/api-guides/usb-serial-jtag-console.html) | ネイティブUSBの構成・制約。C3 UARTスケッチは本プロジェクトで実装 |
| [Arduino CLI](https://arduino.github.io/arduino-cli/latest/installation/)／[Arduino ESP32 Core](https://github.com/espressif/arduino-esp32) | C3スケッチのビルド・USB書き込み。確認版はCore 3.3.7 |
| [Seeed：XIAO ESP32C3 Wi-Fi／アンテナ](https://wiki.seeedstudio.com/XIAO_ESP32C3_WiFi_Usage/) | 基板・外付けアンテナ・Wi-Fi設定の資料 |
| [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy/)／[Native API](https://esphome.io/components/api/) | XIAO側のBLEプロキシと暗号化LAN通信。これらの基盤はESPHomeが提供 |
| [aioesphomeapi](https://github.com/esphome/aioesphomeapi) | Pi側からESPHome APIを使用。RAW広告の購読維持・接続処理は利用版の挙動と実機で確認 |
| [Home Assistant HomeKit Bridge](https://www.home-assistant.io/integrations/homekit/)／[MQTT Lock](https://www.home-assistant.io/integrations/lock.mqtt/) | MQTTの鍵エンティティをAppleのホームへ公開。HomeKit実装・ペアリング基盤はHome Assistant側が提供 |

ESPHomeやHomeKit Bridgeそのものを本プロジェクトが開発したものとはしていません。同梱するのは本プロジェクトの設定・接続コード・手順です。

## 使用する主要ライブラリー

- [Bleak](https://github.com/hbldh/bleak)：ホスト側BLE。
- [dbus-fast](https://github.com/Bluetooth-Devices/dbus-fast)：LinuxのD-Bus／ペアリングエージェント。
- [cryptography](https://github.com/pyca/cryptography)：RSA、AES、scryptと暗号化バックアップ。
- [Eclipse Paho MQTT Python](https://github.com/eclipse-paho/paho.mqtt.python)：MQTTゲートウェイ。
- [pyserial](https://github.com/pyserial/pyserial)：PC側UART通信。
- [pyelftools](https://github.com/eliben/pyelftools)：利用者のAPK内ELFをデータとして読み取る処理。
- [Unicorn](https://github.com/unicorn-engine/unicorn)、[Capstone](https://github.com/capstone-engine/capstone)：非公開の参照データを使った開発時のエミュレーション・逆アセンブル。公開ランタイムの依存ではありません。

配布用コードが直接利用する版は各`requirements*.txt`に記載しています。上記ソフトの本体・ライセンスは各プロジェクトに属し、本リポジトリのMITがそれらへ上書き適用されるものではありません。生成済みESPHome／Arduinoファームを再配布する際の条件は、今回のソースのみの配布とは別に確認する必要があります。

## 実機記録と出典の区別

資料から読んだ一般仕様、旧APK・取得済みROMから解析した内容、合成試験、所有する1個体での実測を区別します。実機結果の公開範囲は[本体](docs/TESTING.ja.md)、[登録](onboarding/TESTING.ja.md)、[有線](wired/TESTING.ja.md)、[中継](relay/TESTING.ja.md)にあります。文鎮化の[整理済み観測一覧](docs/evidence/SEC001.json)は私有記録の要約で、元ログやダンプの転載ではありません。
