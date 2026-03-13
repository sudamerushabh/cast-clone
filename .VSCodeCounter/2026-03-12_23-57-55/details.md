# Details

Date : 2026-03-12 23:57:55

Directory /home/ubuntu/cast-clone/cast-clone-backend/app

Total : 65 files,  9775 codes, 2361 comments, 2353 blanks, all 14489 lines

[Summary](results.md) / Details / [Diff Summary](diff.md) / [Diff Details](diff-details.md)

## Files
| filename | language | code | comment | blank | total |
| :--- | :--- | ---: | ---: | ---: | ---: |
| [cast-clone-backend/app/\_\_init\_\_.py](/cast-clone-backend/app/__init__.py) | Python | 0 | 0 | 1 | 1 |
| [cast-clone-backend/app/api/\_\_init\_\_.py](/cast-clone-backend/app/api/__init__.py) | Python | 14 | 1 | 3 | 18 |
| [cast-clone-backend/app/api/analysis.py](/cast-clone-backend/app/api/analysis.py) | Python | 81 | 10 | 17 | 108 |
| [cast-clone-backend/app/api/graph.py](/cast-clone-backend/app/api/graph.py) | Python | 228 | 19 | 46 | 293 |
| [cast-clone-backend/app/api/graph\_views.py](/cast-clone-backend/app/api/graph_views.py) | Python | 344 | 29 | 71 | 444 |
| [cast-clone-backend/app/api/health.py](/cast-clone-backend/app/api/health.py) | Python | 56 | 4 | 11 | 71 |
| [cast-clone-backend/app/api/projects.py](/cast-clone-backend/app/api/projects.py) | Python | 100 | 7 | 18 | 125 |
| [cast-clone-backend/app/api/websocket.py](/cast-clone-backend/app/api/websocket.py) | Python | 19 | 7 | 8 | 34 |
| [cast-clone-backend/app/config.py](/cast-clone-backend/app/config.py) | Python | 20 | 1 | 5 | 26 |
| [cast-clone-backend/app/main.py](/cast-clone-backend/app/main.py) | Python | 74 | 4 | 17 | 95 |
| [cast-clone-backend/app/models/\_\_init\_\_.py](/cast-clone-backend/app/models/__init__.py) | Python | 34 | 1 | 3 | 38 |
| [cast-clone-backend/app/models/context.py](/cast-clone-backend/app/models/context.py) | Python | 25 | 17 | 20 | 62 |
| [cast-clone-backend/app/models/db.py](/cast-clone-backend/app/models/db.py) | Python | 50 | 1 | 14 | 65 |
| [cast-clone-backend/app/models/enums.py](/cast-clone-backend/app/models/enums.py) | Python | 55 | 1 | 10 | 66 |
| [cast-clone-backend/app/models/graph.py](/cast-clone-backend/app/models/graph.py) | Python | 93 | 12 | 25 | 130 |
| [cast-clone-backend/app/models/manifest.py](/cast-clone-backend/app/models/manifest.py) | Python | 53 | 2 | 22 | 77 |
| [cast-clone-backend/app/orchestrator/\_\_init\_\_.py](/cast-clone-backend/app/orchestrator/__init__.py) | Python | 0 | 1 | 1 | 2 |
| [cast-clone-backend/app/orchestrator/pipeline.py](/cast-clone-backend/app/orchestrator/pipeline.py) | Python | 203 | 49 | 72 | 324 |
| [cast-clone-backend/app/orchestrator/progress.py](/cast-clone-backend/app/orchestrator/progress.py) | Python | 31 | 6 | 11 | 48 |
| [cast-clone-backend/app/orchestrator/subprocess\_utils.py](/cast-clone-backend/app/orchestrator/subprocess_utils.py) | Python | 54 | 26 | 14 | 94 |
| [cast-clone-backend/app/schemas/\_\_init\_\_.py](/cast-clone-backend/app/schemas/__init__.py) | Python | 34 | 1 | 3 | 38 |
| [cast-clone-backend/app/schemas/analysis.py](/cast-clone-backend/app/schemas/analysis.py) | Python | 25 | 4 | 14 | 43 |
| [cast-clone-backend/app/schemas/graph.py](/cast-clone-backend/app/schemas/graph.py) | Python | 47 | 8 | 25 | 80 |
| [cast-clone-backend/app/schemas/graph\_views.py](/cast-clone-backend/app/schemas/graph_views.py) | Python | 51 | 11 | 35 | 97 |
| [cast-clone-backend/app/schemas/projects.py](/cast-clone-backend/app/schemas/projects.py) | Python | 17 | 4 | 14 | 35 |
| [cast-clone-backend/app/services/\_\_init\_\_.py](/cast-clone-backend/app/services/__init__.py) | Python | 20 | 1 | 3 | 24 |
| [cast-clone-backend/app/services/neo4j.py](/cast-clone-backend/app/services/neo4j.py) | Python | 152 | 9 | 30 | 191 |
| [cast-clone-backend/app/services/postgres.py](/cast-clone-backend/app/services/postgres.py) | Python | 28 | 3 | 12 | 43 |
| [cast-clone-backend/app/services/redis.py](/cast-clone-backend/app/services/redis.py) | Python | 16 | 1 | 11 | 28 |
| [cast-clone-backend/app/stages/\_\_init\_\_.py](/cast-clone-backend/app/stages/__init__.py) | Python | 4 | 1 | 3 | 8 |
| [cast-clone-backend/app/stages/dependencies.py](/cast-clone-backend/app/stages/dependencies.py) | Python | 208 | 106 | 88 | 402 |
| [cast-clone-backend/app/stages/discovery.py](/cast-clone-backend/app/stages/discovery.py) | Python | 367 | 109 | 97 | 573 |
| [cast-clone-backend/app/stages/enricher.py](/cast-clone-backend/app/stages/enricher.py) | Python | 285 | 110 | 83 | 478 |
| [cast-clone-backend/app/stages/linker.py](/cast-clone-backend/app/stages/linker.py) | Python | 294 | 110 | 82 | 486 |
| [cast-clone-backend/app/stages/plugins/\_\_init\_\_.py](/cast-clone-backend/app/stages/plugins/__init__.py) | Python | 38 | 6 | 5 | 49 |
| [cast-clone-backend/app/stages/plugins/aspnet/\_\_init\_\_.py](/cast-clone-backend/app/stages/plugins/aspnet/__init__.py) | Python | 4 | 1 | 3 | 8 |
| [cast-clone-backend/app/stages/plugins/aspnet/di.py](/cast-clone-backend/app/stages/plugins/aspnet/di.py) | Python | 187 | 46 | 49 | 282 |
| [cast-clone-backend/app/stages/plugins/aspnet/middleware.py](/cast-clone-backend/app/stages/plugins/aspnet/middleware.py) | Python | 113 | 24 | 26 | 163 |
| [cast-clone-backend/app/stages/plugins/aspnet/web.py](/cast-clone-backend/app/stages/plugins/aspnet/web.py) | Python | 257 | 55 | 60 | 372 |
| [cast-clone-backend/app/stages/plugins/base.py](/cast-clone-backend/app/stages/plugins/base.py) | Python | 95 | 109 | 39 | 243 |
| [cast-clone-backend/app/stages/plugins/entity\_framework/\_\_init\_\_.py](/cast-clone-backend/app/stages/plugins/entity_framework/__init__.py) | Python | 2 | 1 | 3 | 6 |
| [cast-clone-backend/app/stages/plugins/entity\_framework/dbcontext.py](/cast-clone-backend/app/stages/plugins/entity_framework/dbcontext.py) | Python | 385 | 65 | 65 | 515 |
| [cast-clone-backend/app/stages/plugins/hibernate/\_\_init\_\_.py](/cast-clone-backend/app/stages/plugins/hibernate/__init__.py) | Python | 2 | 1 | 3 | 6 |
| [cast-clone-backend/app/stages/plugins/hibernate/jpa.py](/cast-clone-backend/app/stages/plugins/hibernate/jpa.py) | Python | 242 | 36 | 49 | 327 |
| [cast-clone-backend/app/stages/plugins/registry.py](/cast-clone-backend/app/stages/plugins/registry.py) | Python | 213 | 93 | 60 | 366 |
| [cast-clone-backend/app/stages/plugins/spring/\_\_init\_\_.py](/cast-clone-backend/app/stages/plugins/spring/__init__.py) | Python | 4 | 1 | 3 | 8 |
| [cast-clone-backend/app/stages/plugins/spring/data.py](/cast-clone-backend/app/stages/plugins/spring/data.py) | Python | 221 | 49 | 45 | 315 |
| [cast-clone-backend/app/stages/plugins/spring/di.py](/cast-clone-backend/app/stages/plugins/spring/di.py) | Python | 271 | 53 | 46 | 370 |
| [cast-clone-backend/app/stages/plugins/spring/web.py](/cast-clone-backend/app/stages/plugins/spring/web.py) | Python | 117 | 24 | 27 | 168 |
| [cast-clone-backend/app/stages/plugins/sql/\_\_init\_\_.py](/cast-clone-backend/app/stages/plugins/sql/__init__.py) | Python | 0 | 0 | 1 | 1 |
| [cast-clone-backend/app/stages/plugins/sql/migration.py](/cast-clone-backend/app/stages/plugins/sql/migration.py) | Python | 503 | 113 | 129 | 745 |
| [cast-clone-backend/app/stages/plugins/sql/parser.py](/cast-clone-backend/app/stages/plugins/sql/parser.py) | Python | 136 | 29 | 30 | 195 |
| [cast-clone-backend/app/stages/scip/\_\_init\_\_.py](/cast-clone-backend/app/stages/scip/__init__.py) | Python | 3 | 6 | 3 | 12 |
| [cast-clone-backend/app/stages/scip/indexer.py](/cast-clone-backend/app/stages/scip/indexer.py) | Python | 185 | 78 | 57 | 320 |
| [cast-clone-backend/app/stages/scip/merger.py](/cast-clone-backend/app/stages/scip/merger.py) | Python | 211 | 127 | 67 | 405 |
| [cast-clone-backend/app/stages/scip/protobuf\_parser.py](/cast-clone-backend/app/stages/scip/protobuf_parser.py) | Python | 377 | 135 | 116 | 628 |
| [cast-clone-backend/app/stages/transactions.py](/cast-clone-backend/app/stages/transactions.py) | Python | 203 | 82 | 58 | 343 |
| [cast-clone-backend/app/stages/treesitter/\_\_init\_\_.py](/cast-clone-backend/app/stages/treesitter/__init__.py) | Python | 2 | 1 | 3 | 6 |
| [cast-clone-backend/app/stages/treesitter/extractors/\_\_init\_\_.py](/cast-clone-backend/app/stages/treesitter/extractors/__init__.py) | Python | 21 | 7 | 17 | 45 |
| [cast-clone-backend/app/stages/treesitter/extractors/csharp.py](/cast-clone-backend/app/stages/treesitter/extractors/csharp.py) | Python | 696 | 137 | 108 | 941 |
| [cast-clone-backend/app/stages/treesitter/extractors/java.py](/cast-clone-backend/app/stages/treesitter/extractors/java.py) | Python | 573 | 73 | 106 | 752 |
| [cast-clone-backend/app/stages/treesitter/extractors/python.py](/cast-clone-backend/app/stages/treesitter/extractors/python.py) | Python | 633 | 104 | 90 | 827 |
| [cast-clone-backend/app/stages/treesitter/extractors/typescript.py](/cast-clone-backend/app/stages/treesitter/extractors/typescript.py) | Python | 750 | 147 | 130 | 1,027 |
| [cast-clone-backend/app/stages/treesitter/parser.py](/cast-clone-backend/app/stages/treesitter/parser.py) | Python | 173 | 43 | 44 | 260 |
| [cast-clone-backend/app/stages/writer.py](/cast-clone-backend/app/stages/writer.py) | Python | 76 | 39 | 22 | 137 |

[Summary](results.md) / Details / [Diff Summary](diff.md) / [Diff Details](diff-details.md)