"""Post-generation hook: print getting-started instructions."""

import os

PROJECT_SLUG = "{{ cookiecutter.project_slug }}"
PACKAGE_NAME_UPPER = "{{ cookiecutter.package_name_upper }}"


def main():
    print()
    print("=" * 60)
    print(f"  {PROJECT_SLUG} created successfully!")
    print("=" * 60)
    print()
    print("  Next steps:")
    print()
    print(f"    cd {PROJECT_SLUG}")
    print("    make install")
    print("    cp .env.example .env.server")
    print()
    print("  Start local services (Postgres + MinIO):")
    print()
    print("    docker compose up -d")
    print()
    print("  Run migrations and start dev server:")
    print()
    print("    make migrate")
    print("    make run-dev")
    print()
    print("  Open http://localhost:8000")
    print()
    print(f"  Required env vars use the {PACKAGE_NAME_UPPER}_ prefix.")
    print(f"  See .env.example for all configuration options.")
    print()


if __name__ == "__main__":
    main()
