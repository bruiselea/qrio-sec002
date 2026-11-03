# 配布範囲と第三者の権利

`wired/`の独自C3 UARTスケッチ、PC側コード、合成試験、原因資料にも同梱MIT Licenseを適用します。Arduino／ESP32 Core／pyserial等は別途取得し、各プロジェクトのライセンスが適用されます。純正ROMや全EEPROM、個体バックアップ、失敗したSEC001の配備イメージ、私有ログは同梱しません。原因資料の観測一覧は、元記録から個体情報を除いて整理した要約です。

`onboarding/`の独自ソースと説明文にも同梱MIT Licenseを適用します。カード登録用のMQ係数表は、本人が保管する対応旧APKから実行時にメモリー上で参照します。旧APK・`libmq.so`・係数表は配布物に含めず、APKを実行・インストール・自動取得しません。利用者の所有するファイルや解析元の第三者データへ、このMITが再配布許諾を与えるものではありません。ELF解析用pyelftools等の依存には、それぞれのプロジェクトのライセンスが適用されます。

`relay/`の独自ソース、独自プロトコル実装、ESPHome設定、説明文も同梱MIT Licenseの対象です。ESPHome、aioesphomeapi等の依存ソフト自体の権利・ライセンスは各プロジェクトに属します。実際のWi-Fi情報やAPI鍵を含むXIAOファームは同梱しません。

この配布物の独自ツール、独自パッチ、説明文には同梱のMIT Licenseを適用します。MITの対象はこの配布物内の独自部分です。Qrio、Sony、Broadcom、Cypress、Infineon、Apple等からの公式配布・認定ではありません。

以下は含めていません。

- 純正ファームの完全イメージ、EEPROM/ROMダンプ、SDK、旧公式APK
- オーナーカード、シリアル、所有者秘密鍵、回復パスフレーズ、HomeKitのペアリング鍵
- upstream qriohackのソースや写真
- Python依存ライブラリのソース、wheel、ネイティブ実行ファイル

純正コードの再配布許諾はこのプロジェクトでは確認できていません。そのため、配布するのは独自の248バイト分の置換データ、元データのハッシュ、適用ツールです。純正部分は各自が所有する本体から手元で読み出して使います。生成されたイメージや個体バックアップへ、上記MITが第三者の権利まで付与するものではありません。配布する際は生成済みファームや`.private`を追加しないでください。

Bleak、dbus-fast、cryptographyは利用者がPyPIから別途取得します。それぞれのライセンス・配布条件が適用されます。依存の版は`requirements-linux.txt`に固定しています。リリースZIPは依存を内包せず、初回セットアップにはインターネット接続が必要です。

参照: [MIT License](https://opensource.org/license/mit)、[GitHubのライセンス説明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)。
