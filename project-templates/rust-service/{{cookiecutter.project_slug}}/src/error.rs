//! One error type for every handler. Each variant knows its status code;
//! clients get a JSON `{"error": ...}` body, and server errors are logged with
//! their cause but not shown to the client.

use axum::{
    Json,
    http::StatusCode,
    response::{IntoResponse, Response},
};

#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("not found")]
    NotFound,
    #[error("{0}")]
    BadRequest(String),
    #[error("missing or invalid bearer token")]
    Unauthorized,
    #[error("database: {0}")]
    Db(#[from] sqlx::Error),
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let status = match &self {
            Self::NotFound => StatusCode::NOT_FOUND,
            Self::BadRequest(_) => StatusCode::BAD_REQUEST,
            Self::Unauthorized => StatusCode::UNAUTHORIZED,
            Self::Db(_) => StatusCode::INTERNAL_SERVER_ERROR,
        };
        let message = if status.is_server_error() {
            // Runs inside the request's span, so the log line carries its id.
            tracing::error!(error = %self, "request failed");
            "internal error".to_owned()
        } else {
            self.to_string()
        };
        (status, Json(serde_json::json!({ "error": message }))).into_response()
    }
}
