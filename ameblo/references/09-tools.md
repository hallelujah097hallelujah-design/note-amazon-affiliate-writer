# 計測ツール・接続・停止基準

## 接続前提
Web検索・ページ本文取得と、以下の2つの機能を実行環境から探す。環境での表示名が変わっても入出力仕様を照合する。
元GPTのAction認証や設定はスキルに自動移行されない。このスキルに認証情報・APIキー・非公開エンドポイントを埋め込まない。

| 論理名 | 接続済みSEO Article Toolsでのツール名 | 入力 |
| --- | --- | --- |
| countCompetitorArticles | countcompetitorarticles | urls: URL配列、最大10本 |
| countDraftArticle | countdraftarticle | html: 最終HTML全文、target_min: 数値、target_max: 数値 |

接続先のスキーマと説明を実行時に確認する。モデルの推測・手計算、ローカルの別集計で必須Actionの実行結果を代用しない。
Web調査が使えなければ調査済みとせず、必要な接続または情報を示す。

## 競合の計測
1. 原則5本の本文競合を送る。
2. 失敗したURLのみ初回を含め最大3回試す。
3. successが5本なら正式平均、3〜4本なら参考平均とする。
4. 1〜2本なら追加候補を調べる。候補合計は最大10URLまでとする。
5. 最終1〜2本は低信頼の参考値と明示して続行し、最終0本は停止する。
6. 各URLの文字数、success/failed、average_count、target_110、target_min、target_maxを返却値のまま記録する。返却されない値は未返却とし、計算や推測で補わない。
7. 競合由来target_minとtarget_maxを保持し、記事制作target_min = max(競合由来target_min, 7000)とする。
8. 計測用target_max = max(競合由来target_max, 記事制作target_min)とする。競合値の上書きと区別する。

## アメブロHTML互換性
countDraftArticleの説明がGutenberg用の場合も、アメブロHTMLをGutenbergに変換しない。
作成時の2026-10-28に、このセッションで次の基本互換性を実測した。

```html
<h2>見出し</h2><p>本文です。</p><ul><li>項目</li></ul><!-- 手動挿入 -->
```

target_min=10、target_max=20の入力で、character_count=10、achievement_rate=100、status=within_targetが返った。
これはh2・p・ulとコメントを含む短い本文の確認であり、表や長文・すべての装飾の保証ではない。
ツール実装や環境が変わった場合、上記の既知サンプルで基本互換性を再確認する。期待と異なる場合は計測の不整合として扱い、完成判定を停止する。

## 本文の計測
最終HTML全文と記事制作target_min、計測用target_maxを送る。
character_count、achievement_rate、statusおよび返却目標値をそのまま記録する。
最低文字数の合否はcharacter_count >= 記事制作target_minで判定する。statusの名称は勝手に変換・捏造しない。
競合上限の超過だけで不合格とはしないが、重複・冗長・水増しを点検する。
未達なら追加調査→有用な加筆→再監査→再計測を行う。
通信エラーは1回再実行する。再実行後も不能なら停止する。
本文を変更したら再計測する。

## 停止報告
完了工程、未完了工程、停止理由、必要な接続・入力、再開工程を示す。
未接続・未計測を0文字と扱わない。ツールが存在しないのに実行結果を作らない。
「構成だけ」は本文計測不要。競合計測未完了なら未計測の暫定構成として状態を明示する。
