//! Proxy authenticated WP5 signaling to the loopback audio service.
//! 将已鉴权的 WP5 信令代理到本机音频服务。

use std::sync::OnceLock;
use std::time::Duration;

use axum::body::Bytes;
use axum::http::{HeaderMap, Method, Request};
use http_body_util::{BodyExt, Full, Limited};
use hyper_util::client::legacy::{connect::HttpConnector, Client};
use hyper_util::rt::TokioExecutor;
use serde_json::{json, Value};

struct Service {
    token: String,
    origin: String,
    epoch: u64,
    client: Client<HttpConnector, Full<Bytes>>,
}

static SERVICE: OnceLock<Service> = OnceLock::new();

#[derive(Debug)]
pub struct ServiceError {
    pub message: String,
    pub outcome_unknown: bool,
}

impl From<String> for ServiceError {
    fn from(message: String) -> Self { Self { message, outcome_unknown: true } }
}

/// Enable WP5 only with an explicit token and browser origin.
/// 仅在显式提供令牌与浏览器来源时启用 WP5。
pub fn init() -> Result<(), String> {
    let Some(token) = std::env::var_os("IIR_INTERACTION_TOKEN") else { return Ok(()) };
    let token = token.into_string().map_err(|_| "IIR_INTERACTION_TOKEN must be UTF-8")?;
    let origin = std::env::var("IIR_WEB_ORIGIN").map_err(|_| "IIR_WEB_ORIGIN is required")?;
    if token.is_empty() || token.chars().any(char::is_control) {
        return Err("IIR_INTERACTION_TOKEN is invalid".into());
    }
    let uri = origin.parse::<axum::http::Uri>().map_err(|e| e.to_string())?;
    if uri.scheme_str() != Some("https") || uri.authority().is_none()
        || uri.path_and_query().is_some_and(|p| p.as_str() != "/")
        || origin.ends_with('/')
    {
        return Err("IIR_WEB_ORIGIN must be an HTTPS origin without a trailing slash".into());
    }
    SERVICE.set(Service {
        token, origin, epoch: rand::random(),
        client: Client::builder(TokioExecutor::new()).build_http(),
    }).map_err(|_| "WP5 service already initialized".to_string())
}

/// Report whether the dedicated audio service owns the device paths.
/// 返回专用音频服务是否接管设备路径。
pub fn enabled() -> bool { SERVICE.get().is_some() }

/// Enforce the configured browser origin before a WebSocket upgrade.
/// 在 WebSocket 升级前校验配置的浏览器来源。
pub fn origin_allowed(headers: &HeaderMap) -> bool {
    match SERVICE.get() {
        None => true,
        Some(service) => headers.get("origin").and_then(|v| v.to_str().ok()) == Some(&service.origin),
    }
}

fn required<'a>(msg: &'a Value, field: &str) -> Result<&'a str, String> {
    msg.get(field).and_then(Value::as_str).filter(|s| !s.is_empty())
        .ok_or_else(|| format!("缺少字段：{field}"))
}

fn request_spec(owner: &str, msg: &Value) -> Result<(Method, String, Value), String> {
    match required(msg, "action")? {
        "status" => Ok((Method::GET, "/status".into(), Value::Null)),
        "create" => {
            let mode = required(msg, "mode")?;
            if !matches!(mode, "intercom" | "remote_announcement" | "video") {
                return Err("不支持的音频或视频模式".into());
            }
            Ok((Method::POST, "/sessions".into(), json!({"owner": owner, "mode": mode})))
        }
        action @ ("offer" | "delete" | "activate") => {
            let id = required(msg, "session_id")?;
            if id.len() != 32 || !id.bytes().all(|c| c.is_ascii_hexdigit()) {
                return Err("会话标识格式错误".into());
            }
            if action == "delete" {
                return Ok((Method::DELETE, format!("/sessions/{id}?owner={owner}"), Value::Null));
            }
            if action == "activate" {
                return Ok((Method::POST, format!("/sessions/{id}/activate"), json!({"owner": owner})));
            }
            let kind = required(msg, "kind")?;
            let sdp = required(msg, "sdp")?;
            if !matches!(kind, "publish" | "microphone" | "camera") || sdp.len() > 65536 {
                return Err("媒体信令格式错误".into());
            }
            Ok((Method::POST, format!("/sessions/{id}/offer"),
                json!({"owner": owner, "kind": kind, "sdp": sdp})))
        }
        _ => Err("不支持的交互操作".into()),
    }
}

async fn exchange(service: &Service, base: &str, method: Method, path: &str, body: Value)
    -> Result<Value, ServiceError>
{
    let request = Request::builder().method(method).uri(format!("{base}{path}"))
        .header("Authorization", format!("Bearer {}", service.token))
        .header("Content-Type", "application/json")
        .body(Full::new(Bytes::from(body.to_string()))).map_err(|e| e.to_string())?;
    let work = async {
        let response = service.client.request(request).await.map_err(|e| format!("音频服务不可用：{e}"))?;
        let status = response.status();
        let bytes = Limited::new(response.into_body(), 131072).collect().await
            .map_err(|e| format!("音频服务响应无效：{e}"))?.to_bytes();
        if status == axum::http::StatusCode::NO_CONTENT { return Ok(json!({})); }
        let data: Value = serde_json::from_slice(&bytes).map_err(|e| format!("音频服务 JSON 无效：{e}"))?;
        if !status.is_success() {
            return Err(ServiceError { message: format!("音频服务 {status}：{}", data.get("error").unwrap_or(&data)),
                outcome_unknown: status.is_server_error() });
        }
        Ok(data)
    };
    tokio::time::timeout(Duration::from_secs(8), work).await
        .map_err(|_| ServiceError::from("音频服务请求超时，执行结果未知".to_string()))?
}

/// Forward signaling with the server connection ID as the sole owner.
/// 使用服务端连接标识作为唯一所有者转发信令。
pub async fn execute(owner: u64, generation: u64, msg: &Value) -> Result<Value, ServiceError> {
    let service = SERVICE.get().ok_or_else(|| ServiceError { message: "WP5 音频服务未配置".into(), outcome_unknown: false })?;
    let owner_id = format!("{:016x}-{owner}-{generation}", service.epoch);
    let (method, path, body) = request_spec(&owner_id, msg).map_err(|message| ServiceError { message, outcome_unknown: false })?;
    let result = exchange(service, "http://127.0.0.1:8095", method, &path, body).await;
    if result.as_ref().is_err_and(|error| error.outcome_unknown)
        && msg.get("action").and_then(Value::as_str) == Some("create")
    {
        // A lost create response may leave a reservation owned by this connection.
        // 创建响应丢失时，该连接可能仍持有预留。
        close_owner(owner, generation).await;
    }
    result
}

/// Close all media sessions after a control connection leaves.
/// 在控制连接离开后关闭该连接的全部媒体会话。
pub async fn close_owner(owner: u64, generation: u64) {
    if let Some(service) = SERVICE.get() {
        if let Err(error) = exchange(service, "http://127.0.0.1:8095", Method::POST,
            &format!("/owners/{:016x}-{owner}-{generation}/close", service.epoch), json!({})).await
        {
            eprintln!("WP5 连接 {owner} 清理失败：{}", error.message);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn create_forces_server_owner_and_rejects_sos() {
        let (_, _, body) = request_spec("42", &json!({"action":"create","owner":"attacker","mode":"intercom"})).unwrap();
        assert_eq!(body, json!({"owner":"42","mode":"intercom"}));
        assert!(request_spec("42", &json!({"action":"create","mode":"sos"})).is_err());
    }

    #[test]
    fn session_path_and_signal_are_validated_at_browser_boundary() {
        assert!(request_spec("1", &json!({"action":"delete","session_id":"../sos"})).is_err());
        assert!(request_spec("1", &json!({"action":"offer","session_id":"0123456789abcdef0123456789abcdef","kind":"publish","sdp":"x".repeat(65537)})).is_err());
        let (method, path, _) = request_spec("7", &json!({"action":"delete","session_id":"0123456789abcdef0123456789abcdef"})).unwrap();
        assert_eq!(method, Method::DELETE);
        assert_eq!(path, "/sessions/0123456789abcdef0123456789abcdef?owner=7");
    }

    #[test]
    fn activate_uses_server_owner_and_validates_session() {
        let (method, path, body) = request_spec("owner-1", &json!({"action":"activate","session_id":"0123456789abcdef0123456789abcdef","owner":"spoof"})).unwrap();
        assert_eq!(method, Method::POST);
        assert_eq!(path, "/sessions/0123456789abcdef0123456789abcdef/activate");
        assert_eq!(body, json!({"owner":"owner-1"}));
        assert!(request_spec("owner-1", &json!({"action":"activate","session_id":"../bad"})).is_err());
    }

    #[tokio::test]
    async fn loopback_transport_sends_bearer_and_reports_service_failures() {
        use axum::{routing::post, Router};
        let app = Router::new().route("/sessions", post(|headers: HeaderMap, axum::Json(body): axum::Json<Value>| async move {
            assert_eq!(headers["authorization"], "Bearer service-secret");
            assert_eq!(body["owner"], "42");
            (axum::http::StatusCode::CONFLICT, axum::Json(json!({"error":"audio_busy"})))
        }));
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        let service = Service { token: "service-secret".into(), origin: "https://robot.local".into(), epoch: 0,
            client: Client::builder(TokioExecutor::new()).build_http() };
        let error = exchange(&service, &base, Method::POST, "/sessions", json!({"owner":"42"})).await.unwrap_err();
        assert!(!error.outcome_unknown);
        assert!(error.message.contains("409") && error.message.contains("audio_busy"), "{}", error.message);
        server.abort();
    }
}
