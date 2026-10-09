# App 请求签名器

## 无需编译的设置

Windows x64 用户下载完整技能包后，用自己合法取得的[受支持 APK](../docs/supported-apk.md)运行：

```console
python KIT/scripts/xhh_setup.py --apk USER.apk --install-java --confirm
python KIT/scripts/xhh_setup.py --apk USER.apk --account ALIAS --confirm
```

KIT 是解压目录。需要 Python 3.10+，不需要 JDK、Maven 或 Git。若已有 Java 17+ x64 可省略 `--install-java`，也可用 `--java JAVA_EXECUTABLE` 指定。只有显式 opt-in 才下载私有 Temurin JRE，不修改全局环境。完整参数见技能包的 `references/setup.md`。

release 的 `xhh-signer-bootstrap-0.2.0.jar` 包含 JDK-only 入口、实际签名 main、选定的 Unidbg Java overlay 与不可变依赖锁。设置器直接从上游下载锁定 JAR 和源码归档，在本机组装资源 JAR。它不编译 Java，不上传 APK，也不下载本项目重新打包的原生依赖。许可与来源见 [THIRD-PARTY.md](THIRD-PARTY.md)。

每次调用时 bootstrap 先验证精确依赖清单和哈希，再用平台 classloader 的子加载器执行固定 main。实际资源解析必须选中锁定的资源 JAR，覆盖旧 backend JAR 的同名资源。`bundle-inspect` 是原 SDK 的资源和 loader 检查，不代替 bootstrap 的依赖检查。完整性校验不是 OS 沙箱，也不消除本地文件在校验与使用之间被修改的竞态。

设置器另行按发布锁校验实际执行的 loader。原版 `.7` 的日常 CLI 调用仍信任本地 bundle manifest 内的 loader 摘要，不重新推导 bundle 内容地址；若 manifest 和 loader 同时被恶意替换，不能保证执行的仍是发布 JAR。请保护本地运行目录的写权限，不能把哈希检查当作对同用户恶意程序的隔离。

## 维护者构建预编译资产

```console
python signer/scripts/build_precompiled.py --cache signer/target/upstream --out signer/target/release --javac javac
```

仅维护者需要 JDK 17+。构建器验证 `contract/upstream-artifacts.json` 的固定上游字节，编译 API、Android Java 源码和两个当前 factory，不编译或打包 GPL backend hook 类。它生成最终 JAR、源码 ZIP、THIRD-PARTY.md、signer-release.json 和 SHA256SUMS，并更新技能包内的 release 锁。源码 ZIP 内的同一命令可重建，不依赖原仓库或 Maven。

输出中的 `unidbg-resources-2ded0545.jar` 仅供本机验证，严禁作为 release 资产上传。SHA256SUMS 排除它。目标 APK、提取资源、第三方依赖和 JRE 均不上传。旧 fat-JAR 构建仍仅供维护者研究，不能替换新 bootstrap 资产。

2026-10-09 已从公开 Release 下载技能包，在空缓存、无系统 Java/JDK/Maven 的环境安装私有 Temurin JRE 17 并执行真实固定向量签名。移走原 APK 后仍可签名。Easel 的测试账号身份核验、短文本发帖、读回与删除另行通过，详见[分版本验收记录](../docs/skill-kit-acceptance.md)。这些结果不等于新短信登录、全部接口或匿名可见性通过。

该 Java loader 是 Python CLI 使用的本地 App 请求签名器。它通过 Unidbg 执行从用户 APK 提取的 ARM64 原生库，读取一条标准输入请求，并在标准输出返回签名 JSON。它不提供 HTTP 服务，也不包含账号身份。

## 验收状态

版本 0.5.0rc4+standalone.7 已通过本地签名一致性验收，使用的 loader 与 `.6` 验收时的 SHA-256 相同。对受支持 APK 和同一组输入，loader 返回与研究参考一致的 hkey 和 _rnd。nonce 每次生成，因此不用于比较。

Python CLI 已支持 APK 资源准备、bundle 安装与检查，并在 App 请求时调用安装的 loader。公开仓库和 wheel 不包含 APK、提取资源、SO 或 JAR。普通用户使用上方预编译设置入口，不必执行下方旧版构建。

## 旧 fat-JAR 本地构建

构建需要 JDK 17 或更高版本、Git 和 Maven。首次准备依赖还需要访问公开 Unidbg 源码及其构建依赖。

~~~console
cd signer
python scripts/prepare_unidbg.py --work build/unidbg --repo build/maven-repo
mvn -B -Dmaven.repo.local=build/maven-repo package
~~~

准备脚本从公开仓库固定提交 2ded0545d4ae053055f469ef4a4c49e3f15196a7，并应用 JDK 9+ Module 编译修正。直接使用发布的 unidbg-android 0.9.9 会在目标库中出错。当前只有 unicorn2 后端通过验收。

构建生成 signer/target/xhh-signer-loader.jar。该文件只在用户本机创建，不要提交或上传。

## 在 CLI 中安装

先从允许的来源取得[受支持 APK](../docs/supported-apk.md)，再在本地提取资源并安装 bundle：

~~~console
xhh-sdk signer inspect-apk <your.apk>
xhh-sdk signer prepare-apk <your.apk> --out <resources> --confirm
xhh-sdk signer bundle-install --resources <resources> --loader <loader.jar> --loader-sha256 <trusted-sha256> --confirm
xhh-sdk account configure <alias> --set signer_bundle=bundle:<sha256> --confirm
xhh-sdk --account <alias> doctor --offline
~~~

核对输出中的 bundle 引用后，App 签名请求会使用该账号的 bundle。不要复制维护者的 APK、JAR 或资源。摘要证明本地字节与指定值一致，不证明文件来源可信。

离线目录命令不需要 Java。App 签名请求需要 Java、受支持资源和本地 loader。用户应通过短信登录取得已验收的 App 会话。扫码会话在当前测试中被平台拒绝。

## 请求边界

loader 只从标准输入读取协议版本、资源目录、请求路径、时间、账号身份、设备和 App 版本。未知、重复、过长或危险字段会在模拟执行前拒绝。它把诊断写到标准错误，不接收 Cookie、pkey 或网络请求。

协议仍是 1。输入严格解码 UTF-8，只有 resource_dir 允许 Unicode；身份、设备等其他字段仍要求安全 ASCII。

~~~text
protocol=1
resource_dir=<absolute path to prepared resources>
path=<request path>
timestamp=<unix seconds>
identity=<app identity>
imei=<device imei>
device_info=<device model>
os_version=<android version>
app_version=<app version>
~~~

## 合约检查

~~~console
python scripts/verify_contract.py --out <new-dir> [--resources <prepared>]
~~~

合约检查不会启动 Unidbg、加载 APK 原生库、读取账号凭据或访问网络。
