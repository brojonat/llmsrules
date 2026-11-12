// sqlx::migrate!() embeds migrations/ at compile time; without this, adding a
// new .sql file doesn't trigger a rebuild and the binary ships without it.
fn main() {
    println!("cargo:rerun-if-changed=migrations");
}
