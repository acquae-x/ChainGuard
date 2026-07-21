# Phase 5B 收尾批「账户完善」交付材料（2026-07-20）

规格来源：`10_Phase5_总规格.md` 收尾批条目 —— 忘记密码自助（通道未接则维持"管理员重置"兜底并明示）、
企业邀请码（生成/失效/角色预设，替换 mock 加入页）、SSO（复用 rbac.py 既有 OIDC 骨架）、
账号级锁定（连续失败锁定 15 分钟，补足 IP 限流之外的账号维度防爆破）。

本批为收尾批最后一个模块。C2 / C1 / A03 / A04 / C02-C03 / E-3 / C3 / ERP 集成与字段映射
**均未回退、未重写**。**代码未提交，其他未提交文件未清理。**

---

## 1. 变更文件清单

### 后端（ChainGuard/）

| 文件 | 性质 | 说明 |
|---|---|---|
| `src/webapi/account_lifecycle.py` | 新 | 账号锁定、找回密码（含通道降级）、企业邀请码三块主体逻辑 |
| `src/webapi/sso.py` | 新 | 租户级 OIDC：配置读写、authorize、state/nonce、code 换 token、id_token 校验、账号匹配/首次加入 |
| `alembic/versions/20260720_0009_phase5b_account_lifecycle.py` | 新 | users 加 4 列 + 5 张新表 |
| `src/webapi/models.py` | 改 | User 加 `failed_login_count`/`locked_until`/`last_failed_login_at`/`sso_subject`；新增 `PasswordResetRequest`/`InvitationCode`/`InvitationRedemption`/`SsoConfig`/`SsoLoginState` |
| `src/webapi/config.py` | 改（+16 项） | 锁定阈值/时长、IP 限流可配（默认不变）、重置通道与 SMTP、SSO state/超时 |
| `src/webapi/routers/auth.py` | 改（+6 路由） | login 接入账号锁定；新增重置申请/确认、邀请码加入、SSO discover/authorize/callback |
| `src/webapi/routers/imports_settings.py` | 改（+7 路由） | 解锁、重置待办列表、邀请码增删查、SSO 配置读写；用户列表加脱敏与锁定态 |
| `src/webapi/schemas/__init__.py` | 改（+4） | 四个请求模型 |
| `src/webapi/auth/security.py` | 改（+3 行） | `verify_password` 对非 bcrypt 占位串返回 False 而不是 500（仅 SSO 账号会用到） |
| `src/webapi/notifications.py` | 改（+2 规则） | `password_reset_requested` / `account_locked` 复用 D3 的 admin 收件策略 |
| `tests/test_phase5b_account_lifecycle.py` | 新 | 27 例 |
| `tests/conftest.py` | 改（+1） | 测试进程默认加密密钥（SSO 密钥落库需要） |
| `scripts/mock_oidc_server.py` | 新 | 最小 OIDC 提供方（测试替身），pytest 与 E2E 共用 |
| `scripts/seed_phase5b_account_e2e.py` | 新 | 两个隔离租户 + 管理员/成员/待锁账号 |
| `scripts/run_phase5b_account_acceptance.sh` | 新 | 一键重置库 + 起后端/IdP + 跑 Playwright |

### 前端（chainguard-web/）

| 文件 | 性质 | 说明 |
|---|---|---|
| `src/services/account.ts` | 新 | 账户生命周期全部接口，无 mock 分支 |
| `src/components/SsoConfigCard/index.tsx` | 新 | 租户 SSO 配置卡；密钥只写不读 |
| `src/pages/User/SsoCallback.tsx` | 新 | IdP 回调落地页 |
| `src/pages/User/Reset.tsx` | 重写 | 真实申请 + 令牌重置双形态；通道未配置时明示降级 |
| `src/pages/User/Join.tsx` | 重写 | 真实邀请码加入，去掉 mock 短信验证码 |
| `src/pages/Settings/Users.tsx` | 改 | 邀请码管理表 + 解锁操作 + 找回密码待办条；替换假的"生成邀请链接" |
| `src/pages/User/Login.tsx` | 改 | SSO 入口接真实探测；423 账号锁定常驻提示，与 429 IP 限流提示分开 |
| `src/pages/Settings/Integration.tsx` | 改（+2 行） | 挂载 SSO 配置卡 |
| `src/pages/Settings/Integration.test.tsx` | 改（+1 例 +1 mock） | 页面新增依赖需 mock；补 SSO 卡未配置态断言 |
| `src/services/user.ts` | 改（−12 行） | 删除会造成"假成功"的 mock `joinTenant` / `getSsoConfig` |
| `src/components/index.ts`、`config/routes.ts` | 改（各 +1） | 导出与 `/user/sso-callback` 路由 |
| `e2e/account-lifecycle-api-acceptance.spec.ts` | 新 | 真实 Chromium API-mode 验收，20 张截图 |

---

## 2. 关键设计取舍

**IP 限流与账号锁定并存，互不替代。** IP 维度默认仍是 `5/minute`，由
`test_ip_rate_limit_is_independent_of_account_lock` 断言默认值并验证第 6 次不同账号的尝试仍被
429 拦下。账号维度是"同一账号连续 5 次失败锁 15 分钟"，成功登录立即清零。
`LOGIN_IP_RATE_LIMIT` 做成可配置，是因为不放宽 IP 预算就无法在浏览器里单独观测账号锁定
（第 6 个请求会先被 429 挡掉）；验收脚本把它设为 `100/minute`，**默认值未改**。

**通道未配置绝不谎称已发送。** `PASSWORD_RESET_CHANNEL` 默认 `none`，此时申请接口返回
`mode=manual_admin` + "本系统尚未配置邮件/短信通道，无法自助发送重置链接"，同时生成管理员待办
（D3 站内信 + 用户管理页黄条）。SMTP 已配置时才走令牌自助流程；**投递抛异常也会如实降级**为兜底文案，
不写"已发送"。响应对"账号存在/不存在"完全一致（措辞为条件句），因此不能当账号枚举器用。

**密钥一次性原则。** 临时密码、重置令牌、邀请码明文都只在生成的那一次响应里出现，库内只存 sha256；
邀请码列表只回前 4 位 + 掩码。SSO client_secret 与 ERP 凭证同款 Fernet 加密落库，加密不可用时**拒绝保存**，
任何读接口只回 `clientSecretSet: true`，审计详情只记"是否变更"。

**SSO 默认更安全的一侧。** `autoProvision` 默认关闭 —— IdP 认证成功但租户内无对应账号时拒绝登录，
而不是凭空建号。state/nonce 一次性消费，回调后立即删除，重放直接失败。自动建号的账号
password_hash 写非 bcrypt 占位串，密码登录必然失败。

**邀请码的租户由服务端解析。** `POST /auth/join` 只收 code，落哪个租户由码的哈希查出来，
客户端无从指定 —— 这是跨租户注入的主要防线，E2E 与单测都正面验证了这一点。

---

## 3. 实际执行的测试原始输出

### 后端全量（含本批 27 例）

```
$ cd ChainGuard && python -m pytest tests/ -q -p no:randomly
719 passed, 4 skipped, 12 warnings in 206.29s (0:03:26)
```

本批单独跑：

```
$ python -m pytest tests/test_phase5b_account_lifecycle.py -q
27 passed, 2 warnings in 26.65s
```

27 例覆盖：5 次失败锁定 / 锁定期内正确密码仍拒 / 管理员解锁后可登录 / 成功登录重置计数 /
IP 限流仍生效且默认值未改 / 未知账号不泄露存在性 / 通道未配置降级且管理员待办可见可闭环 /
已知与未知账号响应完全一致 / 自助令牌一次性 / 令牌过期 / 令牌只存哈希 / 普通用户不能重置他人密码 /
邀请码明文只回一次 / 列表只有掩码 / 加入落点为签发租户且角色按预设 / 使用留痕 / 用尽为终态 /
失效后拒绝 / 过期后拒绝 / 跨租户不可见不可失效 / 普通用户不能管理邀请码 / 角色必须属于本租户 /
SSO 未配置时明确不可用 / 配置不全拒绝启用 / 密钥不回显且不入审计 / 普通用户不能读写 SSO 配置 /
真实授权码交换成功回调 / state 重放失败 / state 过期失败 / autoProvision 关闭时拒绝陌生账号 /
autoProvision 开启时首次加入 / 域名白名单外拒绝 / 域名不可被两家租户抢注。

### 前端单测 + 类型检查

```
$ cd chainguard-web && npx tsc --noEmit -p tsconfig.json   # exit 0，无输出
$ npm run test
Test Files  18 passed (18)
     Tests  59 passed (59)
```

### 真实 Chromium API-mode 验收

```
$ cd ChainGuard && bash scripts/run_phase5b_account_acceptance.sh
INFO  [alembic.runtime.migration] Running upgrade 20260719_0008 -> 20260720_0009, ...
seeded tenant-acct-e2e-a / tenant-acct-e2e-b

Running 1 test using 1 worker
  ok 1 [chromium] › e2e\account-lifecycle-api-acceptance.spec.ts:64:5 › 账户完善 Chromium API：邀请码、账号锁定、重置降级、SSO、隔离与权限 (21.7s)

  1 passed (28.9s)
```

真后端（uvicorn:8460，隔离 SQLite）+ 真 mock IdP（:8470，真实 302 授权跳转与 `/token` 交换）
+ 真前端 dev（:8100，DATA_MODE=api）。SSO 成功回调是浏览器真的走完 IdP 跳转，不是打桩。

---

## 4. 逐项验收证据（截图在 `ChainGuard/output/phase5b-account/screenshots/`）

| # | 截图 | 证明 |
|---|---|---|
| 01 | `01-user-management.png` | 用户管理页新增「企业邀请码」区 |
| 02 | `02-invitation-generated.png` | 明文邀请码只在生成弹窗出现一次；同屏列表已是 `6ARK********` |
| 03–04 | `03-join-form.png` / `04-joined-tenant-a.png` | 受邀人填码加入，落点为签发租户 A，角色 = 预设的采购人员 |
| 05 | `05-invitation-exhausted-with-trail.png` | 1/1 已用尽 + 已加入成员留痕 |
| 06 | `06-invitation-revoked.png` | 管理员失效邀请码，状态转「已失效」 |
| 07 | `07-account-locked-login.png` | 连续 5 次失败后登录页常驻「账号已锁定 15 分钟」 |
| 08–09 | `08-admin-sees-locked.png` / `09-admin-unlocked.png` | 管理员看到「已锁定」标签并解锁 |
| 10 | `10-unlocked-login-succeeds.png` | 解锁后正确密码可登录 |
| 11 | `11-reset-degraded.png` | 忘记密码明示「当前无法自助重置，请走管理员兜底」，无任何"已发送" |
| 12 | `12-admin-reset-backlog.png` | 管理员侧待办黄条，申请人账号脱敏为 `a***********@chainguard.test` |
| 13–14 | `13-admin-temporary-password.png` / `14-temporary-password-forces-change.png` | 一次性临时密码 + 首登强制改密守卫 |
| 15 | `15-sso-not-configured.png` | 未配置时 SSO 入口明确提示不可用，不展示假成功 |
| 16–17 | `16-sso-card-unconfigured.png` / `17-sso-configured.png` | SSO 配置卡从「未配置客户端密钥」到「已启用」；密钥输入框始终只显示占位提示 |
| 18 | `18-sso-login-success.png` | 走完真实 IdP 授权后以 SSO 身份登入租户 A |
| 19 | `19-tenant-b-isolated.png` | B 租户看不到 A 的邀请码与 SSO 配置 |
| 20 | `20-member-blocked.png` | 普通成员对邀请码/SSO/重置待办/解锁/重置他人密码全部 403 |

---

## 5. 实现过程中发现并修掉的两个真实缺陷

1. **邀请码用尽后状态显示回退成「生效中」**：`_invitation_view` 只从 `active` 行推导用尽/过期，
   而 `redeem_invitation` 已经把落库状态改成了 `exhausted`，于是两边打架。E2E 第 5 步暴露，
   已改为按终态优先判定，并加单测锁定。
2. **邀请码加入 / SSO 回调后被弹回登录页**：`setInitialState` 的 Promise 早于 React 提交返回，
   `layout.onPageChange` 读到未登录态。登录页此前已用 `flushSync` 解决，新增的两个页面漏了同款处理，
   E2E 直接跑出来了，已补齐。

---

## 6. 已知限制

- **邮件通道未在本环境实测**：`PASSWORD_RESET_CHANNEL=smtp` 的自助路径由单测覆盖
  （`_send_reset_email` 被替换为收集器，验证令牌生成/落哈希/一次性/过期），
  **真实 SMTP 投递未跑过**。默认 `none`，产品当前对用户呈现的就是管理员兜底那条路径。
- **SSO 仅支持 HS256 + client_secret 校验 id_token**，沿用 `rbac.py` 骨架的取向；
  RS256/JWKS 轮换未实现。对接只支持 HS256 的 IdP 时需先确认。
- **`GET /auth/sso/discover` 按邮箱域名解析租户**，因此启用 SSO 时域名全局唯一（重复直接 409）。
  同一集团多租户共用一个企业邮箱域的场景本期不支持。
- **短信通道完全未实现**，配置项只保留了 `none`/`smtp` 两种取值。
- **E2E 验收把 IP 限流放宽到 100/minute**，见 §2 说明；IP 维度的默认行为由 pytest 覆盖，
  两者未在同一次运行中同时验证。
- 用户列表的 `account` 字段改为脱敏回显（原为明文）。既有测试
  `test_settings_users_exposes_account_but_never_password_hash` 只要求字段存在，仍通过；
  前端未使用该字段，无 UI 影响。
