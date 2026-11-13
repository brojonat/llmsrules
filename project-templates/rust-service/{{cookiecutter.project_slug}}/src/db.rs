//! The connection pool. Queries live next to the handlers that use them
//! (see `items`); this module only opens the database and migrates it.

use std::{path::Path, str::FromStr, time::Duration};

use sqlx::{
    SqlitePool,
    sqlite::{SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions},
};

pub async fn connect(url: &str) -> Result<SqlitePool, sqlx::Error> {
    let opts = SqliteConnectOptions::from_str(url)?
        .create_if_missing(true)
        // WAL: readers don't block the writer and the writer doesn't block readers.
        .journal_mode(SqliteJournalMode::Wal)
        // Wait for a concurrent write instead of failing with "database is locked".
        .busy_timeout(Duration::from_secs(5))
        .foreign_keys(true);

    // SQLite creates the file but not its directory.
    if let Some(dir) = Path::new(opts.get_filename()).parent() {
        std::fs::create_dir_all(dir).map_err(sqlx::Error::Io)?;
    }

    let db = SqlitePoolOptions::new().connect_with(opts).await?;
    sqlx::migrate!().run(&db).await?;
    Ok(db)
}

/// Each connection to `sqlite::memory:` is its own empty database, so an
/// in-memory pool must hold exactly one connection.
#[cfg(test)]
pub async fn test_pool() -> SqlitePool {
    let db = SqlitePoolOptions::new()
        .max_connections(1)
        .connect("sqlite::memory:")
        .await
        .unwrap();
    sqlx::migrate!().run(&db).await.unwrap();
    db
}
