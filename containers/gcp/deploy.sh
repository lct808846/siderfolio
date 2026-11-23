#!/usr/bin/env bash
set -euo pipefail
umask 077

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
root="$(cd -- "$here/../.." && pwd -P)"
project=astroagent-gcp
compose=(docker compose --project-name "$project" --env-file "$here/.env" -f "$here/docker-compose.yml")

fail() { printf '%s\n' "$*" >&2; exit 1; }

if [[ "${1:-}" == --rag ]]; then
    compose+=(-f "$here/docker-compose.rag.yml")
    shift
fi

action="${1:-}"
if [[ -z "$action" || "$action" == --help ]]; then
    printf '%s\n' \
        'bash containers/gcp/deploy.sh prepare' \
        'bash containers/gcp/deploy.sh [--rag] deploy [--init-db] [--init-compute]' \
        'bash containers/gcp/deploy.sh [--rag] verify' \
        'bash containers/gcp/deploy.sh [--rag] backup <backup-directory>' \
        'bash containers/gcp/deploy.sh [--rag] compose <Compose arguments>'
    exit 0
fi
shift

if [[ "$action" == prepare ]]; then
    [[ "$#" == 0 ]] || fail 'prepare 不接受额外参数。'
    python3 "$here/deploy_env.py" prepare
    exit 0
fi

[[ -f "$here/.env" && ! -L "$here/.env" ]] || fail '请先执行 prepare 并填写 .env。'
[[ "$(stat -c '%a' "$here/.env")" == 600 ]] || fail '请将 GCP .env 的权限设为 600。'

if [[ "$action" == compose ]]; then
    exec "${compose[@]}" "$@"
fi

check_config() {
    # Only the public host and the compute switch make it to stdout.
    "${compose[@]}" config --format json | python3 "$here/deploy_env.py" verify
}

verify_site() {
    local http_code login_code csrf_code private_code health_code attempt
    local curl_args=(--noproxy '*' --silent --output /dev/null --write-out '%{http_code}' --max-time 5)
    local http_target="$public_host:80:127.0.0.1:80"
    local tls_target="$public_host:443:127.0.0.1:443"
    printf '等待 Caddy 签发证书并验证 https://%s …\n' "$public_host"
    for ((attempt = 0; attempt < 40; attempt++)); do
        login_code="$(curl "${curl_args[@]}" --connect-to "$tls_target" "https://$public_host/login")" || login_code=
        [[ "$login_code" == 200 ]] && break
        sleep 5
    done
    [[ "$login_code" == 200 ]] || fail 'HTTPS 登录页未就绪。查看：bash containers/gcp/deploy.sh compose logs --tail=80 ingress backend'
    http_code="$(curl "${curl_args[@]}" --connect-to "$http_target" "http://$public_host/")"
    csrf_code="$(curl "${curl_args[@]}" --connect-to "$tls_target" "https://$public_host/api/v1/auth/csrf")"
    private_code="$(curl "${curl_args[@]}" --connect-to "$tls_target" "https://$public_host/api/v1/conversations")"
    health_code="$(curl "${curl_args[@]}" --connect-to "$tls_target" "https://$public_host/health")"
    printf 'HTTP 跳转 %s，登录页 %s，认证接口 %s，匿名业务接口 %s，内部探针 %s。\n' \
        "$http_code" "$login_code" "$csrf_code" "$private_code" "$health_code"
    [[ "$http_code" == 308 && "$csrf_code" == 200 && "$private_code" == 401 && "$health_code" == 404 ]] ||
        fail '入口或认证校验结果不符合预期。'
}

[[ "$action" == deploy || "$action" == verify || "$action" == backup ]] || fail "不支持的操作：$action"
site="$(check_config)"
read -r public_host compute <<< "$site"
if [[ "$compute" == 1 ]]; then
    compose+=(--profile compute)
fi

if [[ "$action" == verify ]]; then
    [[ "$#" == 0 ]] || fail 'verify 不接受额外参数。'
    verify_site
    exit $?
fi

if [[ "$action" == backup ]]; then
    [[ "$#" == 1 ]] || fail 'backup 需要指定备份目录。'
    [[ -z "$("${compose[@]}" ps --status running -q backend)" ]] ||
        fail '请先停止后端，再制作数据库与文件处于同一恢复点的备份。'
    running="$("${compose[@]}" exec -T postgres psql -U postgres -d astroagent -Atq <<'SQL'
SELECT to_regclass('public.compute_tasks') IS NOT NULL AS ready \gset
\if :ready
SELECT count(*) FROM public.compute_tasks WHERE state IN ('running','cancelling');
\else
SELECT 0;
\endif
SQL
)"
    [[ "$running" == 0 ]] || fail '请等待正在执行或取消的计算结束后再备份。'
    mkdir -p -- "$1"
    destination="$(realpath -- "$1")"
    now="$(date -u +%Y%m%dT%H%M%SZ)"
    stage="$(mktemp -d "${destination}/.siderfolio-${now}.XXXXXX")"
    trap 'rm -rf -- "$stage"' EXIT
    "${compose[@]}" exec -T postgres pg_dump -U postgres -d astroagent -Fc \
        --no-owner --no-acl >"$stage/database.dump"
    "${compose[@]}" exec -T postgres pg_restore --list <"$stage/database.dump" >/dev/null
    "${compose[@]}" run --rm -T --no-deps --entrypoint /bin/sh backend \
        -ec 'tar -C /var/lib/astroagent -cf - .' >"$stage/application.tar"
    tar -tf "$stage/application.tar" >/dev/null
    printf 'created_at=%s\nsite=%s\n' "$now" "$public_host" >"$stage/metadata"
    (cd -- "$stage" && sha256sum database.dump application.tar metadata >SHA256SUMS)
    complete="${destination}/siderfolio-${now}-${stage##*.}"
    mv -T -- "$stage" "$complete"
    trap - EXIT
    printf '已保存一致备份：%s\n' "$complete"
    exit 0
fi

init_db=0
init_compute=0
for option in "$@"; do
    case "$option" in
        --init-db) init_db=1 ;;
        --init-compute) init_compute=1 ;;
        *) fail "不支持的部署选项：$option" ;;
    esac
done
if [[ "$init_db" == 1 ]]; then
    [[ -z "$("${compose[@]}" ps --status running -q backend)" ]] ||
        fail '已有后端运行。常规更新请去掉 --init-db。'
elif ! docker volume inspect "${project}_postgres_data" >/dev/null 2>&1; then
    fail '未找到该实例的数据库卷。全新部署请显式指定 deploy --init-db。'
fi
if [[ "$init_compute" == 1 && "$compute" != 1 ]]; then
    fail '初始化计算表前，请在 .env 中设置 COMPUTE_ENABLED=1。'
fi

export COMPOSE_PARALLEL_LIMIT=1
build=(postgres backend frontend ingress)
if [[ "$compute" == 1 ]]; then
    build+=(compute-worker)
fi
"${compose[@]}" build "${build[@]}"
"${compose[@]}" run --rm --no-deps ingress validate --config /etc/caddy/Caddyfile --adapter caddyfile
"${compose[@]}" up -d --wait --wait-timeout 240 postgres

app_psql() {
    "${compose[@]}" exec -T postgres sh -ec \
        'PGPASSWORD="$ASTROAGENT_DB_PASSWORD" exec psql -h 127.0.0.1 -U astroagent -d astroagent -v ON_ERROR_STOP=1 "$@"' \
        sh "$@"
}

auth_table="$(app_psql -Atqc "SELECT to_regclass('public.auth_meta') IS NOT NULL")"
if [[ "$auth_table" != t ]]; then
    [[ "$init_db" == 1 ]] || fail '身份表未初始化。请停下后端并检查数据库，再显式初始化。'
    "${compose[@]}" run --rm --no-deps backend -m astroagent.identity_cli initialize
fi

if [[ "$compute" == 1 ]]; then
    compute_table="$(app_psql -Atqc "SELECT to_regclass('public.compute_tasks') IS NOT NULL")"
    if [[ "$compute_table" != t ]]; then
        [[ "$init_compute" == 1 ]] ||
            fail '计算表尚未初始化。请显式增加 --init-compute，或将 COMPUTE_ENABLED 改回 0。'
        app_psql < "$root/scripts/compute_schema.sql"
    fi
    # Record the actual image for newly created worker containers and experiment provenance.
    export COMPUTE_IMAGE_ID
    COMPUTE_IMAGE_ID="$(docker image inspect astroagent-gcp-compute-worker:2.0.0 --format '{{.Id}}')"
fi

"${compose[@]}" up -d --no-build --wait --wait-timeout 240 "${build[@]}"
"${compose[@]}" ps
verify_site
