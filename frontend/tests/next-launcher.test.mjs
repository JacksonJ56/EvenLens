import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { rootCertificates } from "node:tls";
import { spawnSync } from "node:child_process";
import { nextEnvironment } from "../scripts/run-next.mjs";

function setup(t) {
  const dir = mkdtempSync(join(tmpdir(), "eventlens-ca-test-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  writeFileSync(join(dir, "ca.pem"), rootCertificates[0]);
  writeFileSync(join(dir, "other.pem"), rootCertificates[1]);
  return dir;
}
test("没有 CA 配置时沿用 Node 默认信任设置", (t) => {
  const dir = setup(t);
  assert.deepEqual(nextEnvironment(dir, { PATH: "test" }), { PATH: "test" });
});
test("本机文件配置在子进程启动前生效，不导出其他密钥", (t) => {
  const dir = setup(t);
  writeFileSync(
    join(dir, ".env.local"),
    "NODE_EXTRA_CA_CERTS=ca.pem\nPRIVATE_SECRET=should-not-export\n",
  );
  const env = nextEnvironment(dir, {});
  assert.equal(env.NODE_EXTRA_CA_CERTS, join(dir, "ca.pem"));
  assert.equal(env.PRIVATE_SECRET, undefined);
  assert.equal(env.NODE_TLS_REJECT_UNAUTHORIZED, undefined);
  const child = spawnSync(
    process.execPath,
    ["-e", "process.stdout.write(process.env.NODE_EXTRA_CA_CERTS)"],
    { env, encoding: "utf8" },
  );
  assert.equal(child.status, 0);
  assert.equal(child.stdout, join(dir, "ca.pem"));
});
test("进程配置优先于本机文件，本机文件优先于 .env", (t) => {
  const dir = setup(t);
  writeFileSync(join(dir, ".env"), "NODE_EXTRA_CA_CERTS=other.pem\n");
  writeFileSync(join(dir, ".env.local"), "NODE_EXTRA_CA_CERTS=ca.pem\n");
  assert.equal(
    nextEnvironment(dir, {}).NODE_EXTRA_CA_CERTS,
    join(dir, "ca.pem"),
  );
  assert.equal(
    nextEnvironment(dir, { NODE_EXTRA_CA_CERTS: "other.pem" })
      .NODE_EXTRA_CA_CERTS,
    join(dir, "other.pem"),
  );
});
test("证书文件丢失或格式错误时明确报错", (t) => {
  const dir = setup(t);
  assert.throws(
    () => nextEnvironment(dir, { NODE_EXTRA_CA_CERTS: "missing.pem" }),
    /不存在或不是有效 PEM/,
  );
  writeFileSync(join(dir, "invalid.pem"), "not a certificate");
  assert.throws(
    () => nextEnvironment(dir, { NODE_EXTRA_CA_CERTS: "invalid.pem" }),
    /不存在或不是有效 PEM/,
  );
});
