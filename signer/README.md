# App 请求签名器

该 Java loader 是 Python CLI 使用的本地 App 请求签名器。它通过 Unidbg 执行从用户 APK 提取的 ARM64 原生库，读取一条标准输入请求，并在标准输出返回签名 JSON。它不提供 HTTP 服务，也不包含账号身份。

## 验收状态

版本 0.5.0rc4+standalone.7 已通过本地签名一致性验收，使用的 loader 与 `.6` 验收时的 SHA-256 相同。对受支持 APK 和同一组输入，loader 返回与研究参考一致的 hkey 和 _rnd。nonce 每次生成，因此不用于比较。

Python CLI 已支持 APK 资源准备、bundle 安装与检查，并在 App 请求时调用安装的 loader。公开仓库和 wheel 不包含 APK、提取资源、SO 或 JAR。用户需在本地取得 APK 并构建运行时文件。

## 本地构建

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
