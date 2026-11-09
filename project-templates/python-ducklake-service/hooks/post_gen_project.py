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
    print("    cp .env.example .env   # then set JWT_SECRET")
    print("    mise run setup")
    print()
    print("  Start local services (Postgres + Garage as S3):")
    print()
    print("    mise run services")
    print()
    print("  Run migrations and start dev server:")
    print()
    print("    mise run migrate")
    print("    mise run dev")
    print()
    print("  Open http://localhost:8000")
    print()
    print(f"  Required env vars use the {PACKAGE_NAME_UPPER}_ prefix.")
    print(f"  See .env.example for all configuration options.")
    print()


if __name__ == "__main__":
    main()
