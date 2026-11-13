//! Bearer-token auth. `Claims` is an extractor: putting it in a handler's
//! arguments is what makes the route require a valid token.

use std::time::{Duration, SystemTime, UNIX_EPOCH};

use axum::{extract::FromRequestParts, http::header, http::request::Parts};
use jsonwebtoken::{Algorithm, DecodingKey, EncodingKey, Header, Validation, decode, encode};
use serde::{Deserialize, Serialize};

use crate::{app::AppState, error::AppError};

/// HS256 keys derived from one shared secret.
pub struct Keys {
    encoding: EncodingKey,
    decoding: DecodingKey,
}

impl Keys {
    pub fn new(secret: &[u8]) -> Self {
        Self {
            encoding: EncodingKey::from_secret(secret),
            decoding: DecodingKey::from_secret(secret),
        }
    }

    /// Returns the token and its expiry (seconds since the epoch).
    pub fn mint(
        &self,
        sub: &str,
        ttl: Duration,
    ) -> Result<(String, u64), jsonwebtoken::errors::Error> {
        let exp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock after 1970")
            .saturating_add(ttl)
            .as_secs();
        let claims = Claims {
            sub: sub.to_owned(),
            exp,
        };
        Ok((encode(&Header::default(), &claims, &self.encoding)?, exp))
    }

    fn verify(&self, token: &str) -> Option<Claims> {
        // Validation checks the signature, the algorithm and `exp`.
        decode::<Claims>(token, &self.decoding, &Validation::new(Algorithm::HS256))
            .ok()
            .map(|data| data.claims)
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Claims {
    pub sub: String,
    pub exp: u64,
}

impl FromRequestParts<AppState> for Claims {
    type Rejection = AppError;

    async fn from_request_parts(parts: &mut Parts, state: &AppState) -> Result<Self, AppError> {
        parts
            .headers
            .get(header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.strip_prefix("Bearer "))
            .and_then(|token| state.keys.verify(token))
            .ok_or(AppError::Unauthorized)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokens_round_trip_and_expire() {
        let keys = Keys::new(b"secret");
        let (token, _) = keys.mint("alice", Duration::from_secs(60)).unwrap();
        assert_eq!(keys.verify(&token).unwrap().sub, "alice");

        assert!(Keys::new(b"other").verify(&token).is_none(), "wrong secret");

        // Expired well past jsonwebtoken's default 60 s leeway.
        let claims = Claims {
            sub: "bob".into(),
            exp: 1_000,
        };
        let stale = encode(&Header::default(), &claims, &keys.encoding).unwrap();
        assert!(keys.verify(&stale).is_none(), "expired");
    }
}
