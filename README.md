# 河砾微站密度巡检图

标准化DBSCAN、噪声比例与邻域连通簇解释。为河砾研究协作组的12位分析与业务人员提供从样本核对、独立worker计算到批准快照交付的完整工作流。

## 真实业务场景

微站环境特征→密度聚类→复访计划；DBSCAN不是地理热点显著性。团队原先将 `station-density-202611-01.csv` 复制到多份人工表格，复核时再逐项对照。三个痛点是口径不可追溯、重复计算易错、业务说明与结果脱节。上游提供合成业务观察，系统承担研究和复核，下游业务人员读取批准快照。全部演示数据是固定随机种子生成的模拟数据。

## 业务模块

1. 业务总览：批次、样本、任务与批准交付账册。
2. 巡测专题：创建/修改来源说明、查看样本、用真实业务字段追加记录；列表分页。
3. 分析配置：冻结来源、参数和全部样本，进入Redis队列。
4. 完整结果：真实算法摘要、专属诊断、全部CSV导出和可恢复失败态。
5. 复访名单与名额：在结果页按分区/噪声组填写抽样数与站点可访日，生成最小标准化距离名单并占用每日名额；名额不足时整单不占位。
6. 复访计划：分析师草案→负责人批准→阅读者下载批准快照。
7. 审计：登录、来源修改、任务worker完成、业务说明批准、名额维护与名单占位等事件。

## 快速启动

```bash
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
# 可重复执行，不覆盖人工修改
docker compose exec -T backend python -m scripts.seed_demo
```

访问 [前端](http://localhost:18246)；[API文档](http://localhost:19246/docs)。数据库仅演示用途映射 `17746`。首次准备依赖和初始化数据库需要等待健康状态：`docker compose ps`，五个服务均需healthy。

| 组件 | 技术与职责 |
|---|---|
| frontend | 原生 HTML / CSS / JS ES Modules，Nginx代理 `/api/` |
| backend | Python3.11 / FastAPI / SQLAlchemy / JWT |
| worker | 独立Python进程，Redis BLPOP队列，持久化结果/CSV/心跳 |
| db | PostgreSQL16，命名卷持久化 |
| redis | Redis7，AOF命名卷 |

恰好五服务，均配置healthcheck；后端/worker依赖数据库与Redis健康，前端依赖后端健康；worker与后端共享 `artifacts` 命名卷。重置演示环境：`docker compose down -v --remove-orphans`，会删除本项目卷。

## 账号与权限

所有演示账号密码：`Research2026!`。

| 邮箱 | 角色 | 权限 |
|---|---|---|
| admin@station-density.demo | admin | 全部录入/执行、批准业务说明 |
| analyst@station-density.demo | analyst | 录入来源/样本、执行、提交说明，无批准权 |
| viewer@station-density.demo | viewer | 只读、导出结果及已批准快照 |

时间在数据库/API中以UTC存储，总览与审计页面明确转换为Asia/Shanghai北京时间。

JWT有效期8小时；PBKDF2盐化哈希保存密码；角色每请求从数据库读取。访客写操作403，匿名访问业务数据401，重复样本409，非法业务字段422，重复批准409。每客户端/路径写请求90次/分钟，超限429。生产使用需修改JWT及演示数据库凭据。

## 实体与字段

Survey / StationReading / DensityRun / VisitPlan 是核心实体；复访抽样另用 `visit_day_quotas`、`visit_rosters`、`visit_roster_items` 与 `visit_reservation_locks`；另有User和Audit。数据库实际表：`surveys` → `station_readings` → `density_runs` → `visit_plans`。样本以固定字段JSON保存，后端按以下字段严格验证，不接受未知字段替代必填值：温度 ℃（`temperature`）、相对湿度 %（`humidity`）、颗粒浓度 μg/m³（`particles`）。

实体贯穿 `backend/src/models`、`schemas`、`services`、`controllers`、`routes`，以及 `frontend/src/api/research.js`、`stores/research.js` 和 `pages`；复访抽样实现在 `models/visit.py`、`schemas/visit.py`、`services/visit.py`、`services/visit_sampling.py`、`routes/visit.py` 与 `pages/visit.js`。`Source.key` 与 `(Record.source_id, reference)` 为自然键；来源改名不会修改已冻结任务输入。业务说明在创建时保存结果快照，批准后从该快照导出。

## 算法与口径

标准化DBSCAN、噪声比例与邻域连通簇解释，全部计算位于 `backend/src/services/algorithm.py`，前端不拟合模型、不生成模拟结果。输入是冻结业务观察及参数，输出summary、专属诊断、逐行计算明细、seed与输入SHA256。CSV包含全部结果行；页面仅预览前30行。参数：

- `eps`：标准化邻域半径 ε，默认 `0.55`。
- `min_samples`：核心点最少邻居数，默认 `5`。

每个特征先标准化，再按密度连通分区；噪声标签表示稀疏样本，不等同污染或地理热点显著性。

失败态：业务字段缺失/非有限数值、参数越界、样本不足、退化特征或结构错误均明确拒绝或将任务标failed，错误消息保存在任务中。可回到来源或配置修正后重新执行，历史失败记录保留。

已知边界：只在温度/湿度/颗粒三个标准化特征上做密度分区；不是地理显著性、风险诊断或自动污染识别。eps敏感，分区编号没有大小顺序；含常量列明确拒绝。

## 复访抽样与名额

从已完成研究的结果页发起：按分区编号与噪声组分别填写抽样数，并可逐站填写可访日（`reference=YYYY-MM-DD` 列表）；未列出的站点视为全部可访日。到组中心的距离使用该任务冻结的标准化均值与尺度，在原始量纲上计算。噪声组取全部噪声行的逐特征均值作为组中心。

求解使用最小费用流：每个站至多入选一次、每个分区恰好达到抽样数、每日占位不超过剩余名额；在满足这些约束的可行组合中，使入选站到各自组中心标准化距离之和最小。若无法满足（例如剩余名额不足或可访日不足），整张名单拒绝写入并返回缺额说明，不占用任何名额。

每日名额由负责人维护（`PUT /api/visit-quotas`，不可低于当天已占位数），所有研究共用；`GET /api/visit-quotas` 返回已用与剩余。抽样建议数按各组站点规模等比分配（`GET /api/visit-suggest?run_id=&total=`）。名单与占位在同一事务中生效；`request_key` 幂等，重试同一请求返回原名单且不重复占位；同一 `request_key` 搭配不同输入返回409。名单可导出CSV（`GET /api/visit-rosters/{id}/export`）。

## 演示数据与一天剧本

固定seed=42，3个来源 ` HL-202611-01/02/03`，每来源240条，共720条业务记录；三个账号、首轮种子任务，以及 `2026-11-20`/`2026-11-21` 各 6 个每日名额。自然键检查后仅插入缺失数据，连跑seed不重复、不覆盖用户修改。`SEED_DEMO=true` 时启动自动执行；失败记录日志但不阻塞服务。首轮任务同样由独立worker真实计算。

1. 09:00 负责人查看三份来源和720条样本。
2. 09:10 分析师选择 `HL-202611-01 秋季常规组`，核对 `station-density-202611-01.csv`。
3. 09:15 在“巡测专题”核对温度 ℃（`temperature`）、相对湿度 %（`humidity`）、颗粒浓度 μg/m³（`particles`），追加编号 `HL-NEW-001` 的样本。
4. 09:20 新建“十一月复核研究”，按默认参数冻结241条输入。
5. 09:21 独立worker消费Redis队列，返回实算结果与输入校验和。
6. 09:25 分析师查看专属诊断及逐行结果，并下载CSV复算。
7. 09:30 提交“十一月业务复核意见”，负责人核对并批准。
8. 09:40 viewer下载批准快照，查看审计中的worker完成与批准事件。
9. 09:45 负责人在完整结果页按分区填写抽样数（含噪声组）与可访日，生成复访名单并占用每日名额；分析师查看名单、重试不重复占位，名额不足时整单不占位。

## 目录与本地开发

```text
frontend/src/api, stores, types, components/common, hooks, pages, router, utils, constants
backend/src/routes, controllers, services, models, schemas, middlewares, utils, constants, config
backend/scripts/seed_demo.py
backend/migrations/001_initial.sql
```

本地后端：Python3.11虚拟环境安装 `backend/requirements.txt`，设置 `DATABASE_URL`、`REDIS_URL`、`ARTIFACT_DIR`，在backend目录运行 `uvicorn src.main:app --reload`；另开终端运行 `python -m src.worker`。原生前端无需编译，推荐以Compose Nginx访问，保证 `/api/` 代理。前端为Google Fonts双字体、oklch色板，离线字体回退serif；1280/768/390响应布局。

| 环境变量 | 默认与说明 |
|---|---|
| COMPOSE_PROJECT_NAME | `station-density`，隔离容器/网络/命名卷 |
| FRONTEND_PORT / BACKEND_PORT / DB_PORT | `18246 / 19246 / 17746` |
| SEED_DEMO | `true` |
| JWT_SECRET | `.env.example`演示值，部署前修改 |
| DATABASE_URL / REDIS_URL | Compose内部连接，定义在compose的env锚点 |
| ARTIFACT_DIR | `/artifacts`，后端worker共享 |

共享枚举：`backend/src/constants/enums.py` 与 `frontend/src/constants/enums.js` 都定义 admin/analyst/viewer、queued/running/completed/failed、draft/approved。后端service检查对应字符串；README为全量值说明。共享前端组件table/status/chart/business跨总览、结果、配置与复核复用；actions hook和format utils负责交互/格式。后端errors与rate_limit是两个中间件。

测试及截图在批根 `test-artifacts/gb-0042/`，不混入源码。独立算法oracle、HTTP完整流程和真实Playwright浏览器流程见该目录 `TESTING.md`。License：MIT。
