---
name: bump-version
description: Bumps the project version in pyproject.toml and updates uv.lock.
---

1. Reads the current version from `pyproject.toml`.
2. Increments the version (defaults to a patch bump).
3. Updates `pyproject.toml` and runs `uv lock` to synchronize the lockfile.
4. Commits the version bump.

```bash
set -e

# Get current version
CURRENT_VERSION=$(grep -m 1 '^version = ' pyproject.toml | sed -E 's/version = "(.*)"/\1/')
echo "ℹ️ Current version: $CURRENT_VERSION"

# Calculate next patch version
# Assumes semver X.Y.Z
IFS='.' read -r major minor patch <<< "$CURRENT_VERSION"
NEXT_PATCH=$((patch + 1))
NEXT_VERSION="$major.$minor.$NEXT_PATCH"

# Allow overriding via argument
if [ -n "$1" ]; then
  NEXT_VERSION=$1
fi

echo "⬆️ Bumping version to: $NEXT_VERSION"

# Update pyproject.toml
sed -i '' "s/^version = \"$CURRENT_VERSION\"/version = \"$NEXT_VERSION\"/" pyproject.toml

# Update uv.lock
echo "🔄 Updating uv.lock..."
uv lock

# Commit changes (will abort if other uncommitted changes exist)
echo "💾 Committing version bump..."
git add pyproject.toml uv.lock
git commit -m "chore: bump version to $NEXT_VERSION"

echo "✅ Version bumped and committed."
```
