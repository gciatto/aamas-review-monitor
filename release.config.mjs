let dryRun = (process.env.RELEASE_DRY_RUN || "false").toLowerCase() === "true";

// Releases go to GitHub only: the wheel and sdist are attached to the GitHub release (and kept
// as workflow artifacts by deploy.yml). Nothing is published to PyPI.
const prepareCmd = `uv version \${nextRelease.version} && uv build`;

import config from 'semantic-release-preconfigured-conventional-commits' with {type: 'json'};

config.plugins.push(
    ["@semantic-release/exec", {
        "prepareCmd": prepareCmd,
    }]
)

if (!dryRun) {
    config.plugins.push(
        ["@semantic-release/github", {
            "assets": [
                // Not dist/*: `uv build` also writes dist/.gitignore, which would be uploaded.
                { "path": "dist/*.whl" },
                { "path": "dist/*.tar.gz" },
            ]
        }],
        ["@semantic-release/git", {
            "assets": [
                "CHANGELOG.md",
                "pyproject.toml",
                "uv.lock"
            ],
            "message": "chore(release): ${nextRelease.version} [skip ci]\n\n${nextRelease.notes}"
        }]
    );
}

export default config;
