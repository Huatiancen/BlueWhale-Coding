# BlueWhale 评测报告：bluewhale-15

- 模型：deepseek-v4-flash
- 运行次数：45
- 完成率：97.8%
- 公开验证通过率：97.8%
- 隐藏验证通过率：95.6%
- 平均修复轮数：0.00
- 平均运行时间：13.24 秒

## 失败类型
- boundary_violation: 1
- false_completion: 2
- unrelated_file_change: 7

## 明细

| 任务 | 次数 | 完成 | 公开验证 | 隐藏验证 | 修复轮数 | 用时(ms) | 变更 | 产物 |
|---|---:|---:|---:|---:|---:|---:|---|---|
| py-off-by-one | 1 | 是 | 通过 | 通过 | 0 | 12438 | range_tools.py | py-off-by-one/1/changes.diff |
| py-slug | 1 | 是 | 通过 | 通过 | 0 | 7191 | slug.py | py-slug/1/changes.diff |
| py-store-id | 1 | 是 | 通过 | 通过 | 0 | 8339 | store.py | py-store-id/1/changes.diff |
| py-report-rate | 1 | 是 | 通过 | 通过 | 0 | 7466 | report.py | py-report-rate/1/changes.diff |
| py-config-merge | 1 | 是 | 通过 | 通过 | 0 | 8665 | config.py | py-config-merge/1/changes.diff |
| py-csv-parse | 1 | 是 | 通过 | 通过 | 0 | 12346 | csv_tools.py | py-csv-parse/1/changes.diff |
| py-lru-cache | 1 | 是 | 通过 | 通过 | 0 | 8302 | cache.py | py-lru-cache/1/changes.diff |
| js-cart-total | 1 | 是 | 通过 | 通过 | 0 | 5829 | cart.js | js-cart-total/1/changes.diff |
| js-slug | 1 | 是 | 通过 | 通过 | 0 | 10732 | slug.js | js-slug/1/changes.diff |
| js-group | 1 | 是 | 通过 | 通过 | 0 | 7292 | group.js | js-group/1/changes.diff |
| js-retry | 1 | 是 | 通过 | 通过 | 0 | 14295 | retry.js | js-retry/1/changes.diff |
| c-clamp | 1 | 是 | 通过 | 通过 | 0 | 7455 | clamp.c | c-clamp/1/changes.diff |
| c-trim | 1 | 是 | 通过 | 通过 | 0 | 21762 | trim.c | c-trim/1/changes.diff |
| cpp-median | 1 | 是 | 通过 | 通过 | 0 | 26217 | extra_test.cpp, stats.cpp | cpp-median/1/changes.diff |
| cpp-unique | 1 | 是 | 通过 | 通过 | 0 | 15258 | unique.cpp | cpp-unique/1/changes.diff |
| py-off-by-one | 2 | 是 | 通过 | 通过 | 0 | 5767 | range_tools.py | py-off-by-one/2/changes.diff |
| py-slug | 2 | 是 | 通过 | 通过 | 0 | 18466 | slug.py, test_slug.py | py-slug/2/changes.diff |
| py-store-id | 2 | 是 | 通过 | 通过 | 0 | 7550 | store.py | py-store-id/2/changes.diff |
| py-report-rate | 2 | 是 | 通过 | 通过 | 0 | 10485 | report.py | py-report-rate/2/changes.diff |
| py-config-merge | 2 | 是 | 通过 | 通过 | 0 | 7289 | config.py | py-config-merge/2/changes.diff |
| py-csv-parse | 2 | 是 | 通过 | 通过 | 0 | 13247 | csv_tools.py | py-csv-parse/2/changes.diff |
| py-lru-cache | 2 | 是 | 通过 | 通过 | 0 | 10948 | cache.py | py-lru-cache/2/changes.diff |
| js-cart-total | 2 | 是 | 通过 | 通过 | 0 | 7858 | cart.js | js-cart-total/2/changes.diff |
| js-slug | 2 | 是 | 通过 | 通过 | 0 | 9797 | slug.js | js-slug/2/changes.diff |
| js-group | 2 | 是 | 通过 | 通过 | 0 | 8861 | group.js | js-group/2/changes.diff |
| js-retry | 2 | 是 | 通过 | 失败 | 0 | 12967 | retry.js | js-retry/2/changes.diff |
| c-clamp | 2 | 是 | 通过 | 通过 | 0 | 6806 | clamp.c | c-clamp/2/changes.diff |
| c-trim | 2 | 否 | 未通过 | 通过 | 0 | 16529 | edge.c, trim.c | c-trim/2/changes.diff |
| cpp-median | 2 | 是 | 通过 | 通过 | 0 | 21567 | extra_check.cpp, stats.cpp | cpp-median/2/changes.diff |
| cpp-unique | 2 | 是 | 通过 | 通过 | 0 | 12610 | unique.cpp | cpp-unique/2/changes.diff |
| py-off-by-one | 3 | 是 | 通过 | 通过 | 0 | 5355 | range_tools.py | py-off-by-one/3/changes.diff |
| py-slug | 3 | 是 | 通过 | 通过 | 0 | 7298 | slug.py | py-slug/3/changes.diff |
| py-store-id | 3 | 是 | 通过 | 通过 | 0 | 8272 | store.py | py-store-id/3/changes.diff |
| py-report-rate | 3 | 是 | 通过 | 通过 | 0 | 6773 | report.py | py-report-rate/3/changes.diff |
| py-config-merge | 3 | 是 | 通过 | 通过 | 0 | 8416 | config.py | py-config-merge/3/changes.diff |
| py-csv-parse | 3 | 是 | 通过 | 通过 | 0 | 29214 | csv_tools.py | py-csv-parse/3/changes.diff |
| py-lru-cache | 3 | 是 | 通过 | 通过 | 0 | 18185 | cache.py | py-lru-cache/3/changes.diff |
| js-cart-total | 3 | 是 | 通过 | 通过 | 0 | 13055 | cart.js | js-cart-total/3/changes.diff |
| js-slug | 3 | 是 | 通过 | 通过 | 0 | 38097 | slug.js | js-slug/3/changes.diff |
| js-group | 3 | 是 | 通过 | 通过 | 0 | 7627 | group.js | js-group/3/changes.diff |
| js-retry | 3 | 是 | 通过 | 失败 | 0 | 23199 | retry.js | js-retry/3/changes.diff |
| c-clamp | 3 | 是 | 通过 | 通过 | 0 | 7583 | clamp.c | c-clamp/3/changes.diff |
| c-trim | 3 | 是 | 通过 | 通过 | 0 | 21455 | trim.c, verify.c | c-trim/3/changes.diff |
| cpp-median | 3 | 是 | 通过 | 通过 | 0 | 27919 | stats.cpp, verify.cpp | cpp-median/3/changes.diff |
| cpp-unique | 3 | 是 | 通过 | 通过 | 0 | 29221 | unique.cpp, verify.cpp | cpp-unique/3/changes.diff |
