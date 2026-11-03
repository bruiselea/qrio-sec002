# 有線バックアップと純正起動先の復旧キット

日本語 | [English](README.en.md)

自分のQ-SL1へUARTで接続し、EEPROMを暗号化保存し、**純正DS1と元のSS1が残っている場合に限り、起動マーカー1バイトを戻す**ためのツールです。Windows PCから直接使えます。ラズパイは必須ではありません。

このキットは全消去・全EEPROM書き戻し・DS1/DS2の再書き込みを行いません。壊れた純正ファームを再生成する機能はありません。[文鎮化の原因と実施記録](../docs/BOOT_FAILURE.ja.md)、[検証範囲](TESTING.ja.md)も確認してください。

**公開版の復旧コマンド一式は、実機通し試験未実施です。** 所有する1個体で使ったC3中継、ROM通信、読み出し、WP設定、起動先変更を公開用に整理したものです。既に稼働中の玄関の鍵には、この公開版を再実行していません。過去の最初の「マーカー書込ACK」は実際には書けておらず、その後の復旧はDEV001の配置・選択を含む手順で実証しました。単独の1バイト操作だけで純正起動した、という記録ではありません。

## 必要なもの

| 必要なもの | 条件 |
| --- | --- |
| 自分のQ-SL1 | **ドアから外し、左右の電池を抜いて配線する** |
| 正常なCR123A電池 | 本体への給電に使用 |
| 3.3VロジックのUSB UART | 実証したのはC3 SuperMini＋同梱スケッチ。通常のUSB UARTは`--adapter uart-3v3`で選択可能だが実機未確認 |
| 12ピン・0.5mmピッチFPCへの接続手段 | 接点面・番号を確認した変換基板、または適切な細線の接続 |
| 配線3本、テスター | TX、RX、共通GND。隣接端子の短絡と論理電圧を確認 |
| Python 3.11以上のPC | Windows／Linux。C3のビルドにはArduino CLIとESP32 Core 3.3.7を別途使用 |
| **同じ個体の正常時バックアップ** | 書き込みには必須。純正1.4.01のDS1と、正常起動したSS1を含む完全な64KiB `.qsb` |

正常時バックアップがなくても、新しい有線バックアップの保存はできます。**保存できたことだけでは、そのデータが正常起動する証明にはなりません。** 対象は既知の純正DS1配置とROMだけです。別個体の全EEPROMを移植しません。

## 1. PCの環境を用意

リポジトリの最新ソースを取得してルートで実行します。v0.1.0 Release ZIPにはこのキットは入っていません。

```powershell
python -m venv .venv-wired
.venv-wired\Scripts\python -m pip install -r requirements-wired.txt
.venv-wired\Scripts\python -m wired --help
$qrioWired = "$env:USERPROFILE\.qrio-sl1\wired"
New-Item -ItemType Directory -Force $qrioWired | Out-Null
```

Linuxでは`.venv-wired/bin/python`と、本人だけが読める`~/.qrio-sl1/wired`などを使います。保存前に`umask 077`と親フォルダーのモード700を設定します。Windowsでは本人以外が読めないNTFS ACLの場所を使います。バックアップは既存の[ポータブル暗号化形式](../qsl1sec/private.py)と共通で、Windowsアカウントへの依存なく復号できます。パスフレーズは端末で非表示入力し、12文字以上を指定します。

## 2. C3をUART変換器にする場合

普通のUSB UARTを用意できていれば、この節は不要です。C3は**Q-SL1と他の回路を全部外してから**USBへ接続します。残したいC3のプログラムは本人の手順で先にバックアップします。このキットは元のC3ファームの自動保存・復元は行いません。

Arduino CLIを[公式配布](https://arduino.github.io/arduino-cli/latest/installation/)から用意し、ESP32 Coreを指定版で入れます。

```powershell
arduino-cli core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core install esp32:esp32@3.3.7 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
.venv-wired\Scripts\python wired\build_bridge.py --output-dir "$qrioWired\c3-build"
```

`--cli`でArduino CLI実行ファイル、`--config`で本人のCLI設定を指定できます。ビルド先は新しいフォルダーに限ります。ビルド処理はポートを開かず、機器へ書き込みません。生成物は`c3-build/firmware/`にあります。C3用のビルド済みバイナリやコンパイラーは同梱していません。

```powershell
.venv-wired\Scripts\python -m wired ports
arduino-cli upload --fqbn "esp32:esp32:esp32c3:CDCOnBoot=cdc,FlashSize=4M,FlashMode=dio,DebugLevel=none" --port COM_PORT --input-dir "$qrioWired\c3-build\firmware" wired\c3_uart_bridge
```

`COM_PORT`を本人のC3のポートに置き換えます。書き込み先はC3です。4MB・DIO・ネイティブUSB CDC有効のESP32-C3構成で、XIAO中継用ファームとは別物です。同じ基板を使う場合、元の中継プログラムは置き換わります。

USBを抜き、C3の**GPIO4とGPIO5だけ**を線1本で接続してUSBを戻します。Q-SL1へは接続しません。

```powershell
.venv-wired\Scripts\python -m wired loopback --port COM_PORT --qsl1-disconnected
```

65,536バイトの往復一致を確認します。ランダムなデータも送るため、Q-SL1へ向けてこの試験を実行しません。終了後、USBを抜いてGPIO4–GPIO5間の線を必ず外します。

## 3. Q-SL1へ3本を接続

**Q-SL1の電池とC3のUSBを両方外した状態**で配線します。F番号はQ-SL1側フラットケーブルの端子番号です。コネクターの表裏・印刷番号との対応を現物とテスターで確認します。

| Q-SL1 | C3 SuperMini | 普通の3.3V USB UARTの場合 |
| --- | --- | --- |
| **F9：Programming RX** | **GPIO5：TX** | TX |
| **F10：Programming TX** | **GPIO4：RX** | RX |
| **F11：GND** | **GND** | GND |

**F1・F2・F3、C3やUART変換器の5V・3V3/VCCはつなぎません。** 本体は電池で給電します。UART信号は115200bps、8N1、フロー制御なし。5V UARTやRS-232は使いません。

C3のUSBを先に接続してTXをアイドルHighにしてから、本体へ電池を入れます。対象個体ではこの順でROMプログラミングモードへ入りました。この状態でアプリの起動音・広告が出ないことは、それだけでは故障を意味しません。UART RXのリセット時レベルと起動モードについては[メーカーの説明](https://community.infineon.com/t5/Smart-Bluetooth/How-image-is-validated-during-bootup/td-p/198938)も参照します。

先行調査の端子表・写真は[bakueikozo/qriohack](https://github.com/bakueikozo/qriohack)を参照します。同リポジトリの写真・コードや、純正SDKは転載していません。

[honeylabの先行記事](https://honeylab.hatenablog.jp/entry/2023/06/03/090731)も参照しました。使用した資料・固定参照版・本プロジェクト側の実装範囲は[出典一覧](../SOURCES.md)にあります。

## 4. ROM応答と故障時バックアップを確認

シリアルモニターなど、同じポートを使うアプリを閉じてから実行します。

```powershell
.venv-wired\Scripts\python -m wired probe --port COM_PORT --device-off-door
.venv-wired\Scripts\python -m wired backup --port COM_PORT --device-off-door --output-dir "$qrioWired\fault-01"
```

普通のUSB UARTなら両方へ`--adapter uart-3v3`を追加します。ソフトでは信号電圧を検証できないため、3.3Vロジックであることを物理的に確認します。

`probe`は標準HCI機種情報照会、`backup`は64KiBの独立2回読み出しを行います。RAM・EEPROMへの書き込みはありません。`fault-01/capture-pass1.qsb`と`capture-pass2.qsb`をそれぞれ暗号化保存・復号照合し、2回のデータが同一の場合だけ完了します。既存フォルダーは再使用しません。不一致で止まっても、保存済みの暗号化ファイルは残します。

## 5. 正常時バックアップを用意

正常時にこのキットで採った完全な`.qsb`、または[無線キット](../docs/WIRELESS_INSTALL.ja.md)の`original.qsb`を使えます。正常な電池起動を確認した同じ個体の控えを指定します。

以前のWindows用`.dpapi.json`がある場合、**保存した本人のWindowsアカウントとPC**で次のオフライン変換ができます。

```powershell
.venv-wired\Scripts\python -m wired import-dpapi --input "C:\path\to\your-original.dpapi.json" --output "$qrioWired\original.qsb"
```

元のDPAPIファイルは変更せず、完全な64KiB・元の整合性を検査し、新しいパスフレーズで暗号化します。平文ファームを書き出しません。本人のWindowsで復号できない場合の回避機能はありません。故障時の控えを変換しただけでは、正常時バックアップの代わりにはなりません。

```powershell
.venv-wired\Scripts\python -m wired inspect --backup "$qrioWired\original.qsb"
.venv-wired\Scripts\python -m wired inspect --backup "$qrioWired\fault-01\capture-pass1.qsb"
```

純正DS1・SS1構造とマーカーを確認します。全EEPROMのハッシュ、Bluetoothアドレス、鍵のバイト列は表示しません。

## 6. まずオフライン計画、次に必要な場合だけ実行

```powershell
.venv-wired\Scripts\python -m wired restore-stock --original "$qrioWired\original.qsb" --snapshot "$qrioWired\fault-01\capture-pass1.qsb"
```

既定は**ポートを開かない計画確認**です。純正DS1は26,845バイトの固定ハッシュ、SS1は先頭以外の39バイトが正常時と同一、先頭マーカーは00または01であることを要求します。別の版・破損・不一致を強制する引数はありません。SS2やDS2が不完全でも、それらを修復せず純正SS1を選ぶ方式です。

実行する場合は、ドアから外した状態で新しい保存先を指定します。

```powershell
.venv-wired\Scripts\python -m wired restore-stock --original "$qrioWired\original.qsb" --snapshot "$qrioWired\fault-01\capture-pass1.qsb" --execute --port COM_PORT --device-off-door --output-dir "$qrioWired\restore-01"
```

正常時・故障時それぞれの復号パスフレーズと、今回の保存用の新しいパスフレーズを非表示で入力します。

1. 実機から直前に64KiBを2回取得し、それぞれ暗号化保存・照合。指定した故障時スナップショットとも完全一致しなければ中止。
2. ROMの2領域の指紋、HCI版、WP設定・16バイトページ設定を照合。異なる場合は書かない。
3. 既存ROMのWPコールバック参照とポート指定だけを一時的に設定。新規実行コード・minidriverは送らない。
4. EEPROMアドレス0へ`01`を1回だけ要求。成功応答だけでは完了しない。
5. 全64KiBを再読取・暗号化保存し、**残り65,535バイトが不変**で予定値と一致することを確認。
6. 一時的なRAM設定を元へ戻して読み戻す。起動の確認は次の節で別に行う。

先頭が既に01なら永続書き込みを行いません。`result.receipt.json`へ段階と確認結果を記録します。通信断や短い送信で書き込みを再送しません。書き込み後の応答喪失では結果不明になり得るため、新しく`backup`してから再判断します。途中失敗で一時設定を戻せなかった場合も完了とは扱いません。

## 7. 配線を外し、電池だけで起動確認

本体の電池を全部抜く → C3のUSBを抜く → F9・F10・F11の3本を外す → 15秒ほど待つ → 本体の電池だけ戻す、の順で通常起動を確認します。UARTをつないだままの起動判定をしません。

起動音・ランプ、BLE広告・版表示、本人の所有者鍵によるReadStatusを順に確認します。復旧CLIはモーターを動かしません。`completed: true`は**起動先復元と読み戻しの完了**であり、通常起動・施解錠の証明ではありません。記録の`normal_boot_verified`は自動でtrueにしません。

純正へ戻るとSEC002の対策もその起動では適用されません。HomeKitを再開する前に、起動した版と動作を本人が確認してください。純正DS1・SS1が壊れている、バックアップがない、UARTが応答しない場合を、この1バイト復旧で直せるとは案内していません。

バックアップ・暗号化済みファイル・本人の実行記録・生成物はGitHubへ追加しません。公開には独自ソース、手順、合成試験だけを使います。
