//! An example resource: the SQL and the handlers for `/items`. Copy this
//! module for each new resource and register its routes in `app::app`.
//!
//! SQL is plain strings, checked when it runs: `query_as` maps rows onto a
//! `#[derive(FromRow)]` struct by column name, `?` placeholders take `.bind()`
//! values. The tests run every query, so a typo fails `cargo test`.

use axum::{
    Json, Router,
    extract::{Path, Query, State},
    http::StatusCode,
    routing::get,
};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

use crate::{app::AppState, auth::Claims, error::AppError};

#[derive(Debug, Serialize, FromRow)]
pub struct Item {
    pub id: i64,
    pub name: String,
    pub created_by: String,
    pub created_at: String,
}

#[derive(Deserialize)]
pub struct NewItem {
    pub name: String,
}

#[derive(Deserialize)]
pub struct Page {
    #[serde(default = "default_limit")]
    limit: i64,
    #[serde(default)]
    offset: i64,
}

fn default_limit() -> i64 {
    20
}

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/items", get(list).post(create))
        .route("/items/{id}", get(fetch).delete(remove))
}

async fn list(
    State(app): State<AppState>,
    Query(page): Query<Page>,
) -> Result<Json<Vec<Item>>, AppError> {
    let items = sqlx::query_as(
        "SELECT id, name, created_by, created_at FROM items
         ORDER BY id DESC LIMIT ? OFFSET ?",
    )
    .bind(page.limit.clamp(1, 100))
    .bind(page.offset.max(0))
    .fetch_all(&app.db)
    .await?;
    Ok(Json(items))
}

async fn fetch(State(app): State<AppState>, Path(id): Path<i64>) -> Result<Json<Item>, AppError> {
    sqlx::query_as("SELECT id, name, created_by, created_at FROM items WHERE id = ?")
        .bind(id)
        .fetch_optional(&app.db)
        .await?
        .map(Json)
        .ok_or(AppError::NotFound)
}

/// `Claims` in the arguments makes this route require a token. Extractors
/// that read the body (`Json`) must come last.
async fn create(
    State(app): State<AppState>,
    claims: Claims,
    Json(new): Json<NewItem>,
) -> Result<(StatusCode, Json<Item>), AppError> {
    let name = new.name.trim();
    if name.is_empty() || name.chars().count() > 200 {
        return Err(AppError::BadRequest("name must be 1-200 characters".into()));
    }
    // One statement, so it commits whole or not at all, even if the client
    // disconnects mid-request.
    let item = sqlx::query_as(
        "INSERT INTO items (name, created_by) VALUES (?, ?)
         RETURNING id, name, created_by, created_at",
    )
    .bind(name)
    .bind(&claims.sub)
    .fetch_one(&app.db)
    .await?;
    tracing::info!(sub = %claims.sub, "item created");
    Ok((StatusCode::CREATED, Json(item)))
}

async fn remove(
    State(app): State<AppState>,
    _claims: Claims,
    Path(id): Path<i64>,
) -> Result<StatusCode, AppError> {
    let res = sqlx::query("DELETE FROM items WHERE id = ?")
        .bind(id)
        .execute(&app.db)
        .await?;
    match res.rows_affected() {
        0 => Err(AppError::NotFound),
        _ => Ok(StatusCode::NO_CONTENT),
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use axum::{body::Body, http::Request};

    use crate::app::tests::{send, test_state};

    fn bearer(state: &crate::app::AppState) -> String {
        let (token, _) = state.keys.mint("alice", Duration::from_secs(60)).unwrap();
        format!("Bearer {token}")
    }

    fn post(name: &str, auth: Option<&str>) -> Request<Body> {
        let mut req = Request::post("/items").header("content-type", "application/json");
        if let Some(auth) = auth {
            req = req.header("authorization", auth);
        }
        req.body(Body::from(serde_json::json!({ "name": name }).to_string()))
            .unwrap()
    }

    #[tokio::test]
    async fn writes_need_a_token() {
        let state = test_state().await;
        let (status, _, body) = send(&state, post("widget", None)).await;
        assert_eq!(status, 401);
        assert!(body.contains("bearer token"), "{body}");

        let (status, _, _) = send(&state, post("widget", Some("Bearer nope"))).await;
        assert_eq!(status, 401);
    }

    #[tokio::test]
    async fn create_fetch_list_delete() {
        let state = test_state().await;
        let auth = bearer(&state);

        let (status, _, body) = send(&state, post("  widget ", Some(&auth))).await;
        assert_eq!(status, 201, "{body}");
        let item: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(item["name"], "widget");
        assert_eq!(item["created_by"], "alice");
        let id = item["id"].as_i64().unwrap();

        let get = |uri: String| Request::get(uri).body(Body::empty()).unwrap();
        let (status, _, body) = send(&state, get(format!("/items/{id}"))).await;
        assert_eq!(status, 200, "{body}");

        send(&state, post("gadget", Some(&auth))).await;
        let (_, _, body) = send(&state, get("/items?limit=1".into())).await;
        let page: Vec<serde_json::Value> = serde_json::from_str(&body).unwrap();
        assert_eq!(page.len(), 1);
        assert_eq!(page[0]["name"], "gadget", "newest first");

        let delete = Request::delete(format!("/items/{id}"))
            .header("authorization", &auth)
            .body(Body::empty())
            .unwrap();
        assert_eq!(send(&state, delete).await.0, 204);
        assert_eq!(send(&state, get(format!("/items/{id}"))).await.0, 404);
    }

    #[tokio::test]
    async fn bad_input_is_a_400() {
        let state = test_state().await;
        let auth = bearer(&state);
        let (status, _, body) = send(&state, post("   ", Some(&auth))).await;
        assert_eq!(status, 400);
        assert!(body.contains("1-200"), "{body}");
    }
}
