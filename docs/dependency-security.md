# Dependency security ownership and coverage

Ameyanagi owns security triage for these repositories: akari, hibana, kagerou,
moji, mojotui, nagare, nami, nerai, sen, shuhafft, yomi, yuragi, kumihan and
mojo-channel. Review actionable alerts within one business day for critical/high
severity and within five business days for other severities. Record applicability,
a proposed remediation version and a target date; prioritize active exploitation
immediately. Report unpatched vulnerabilities using the affected repository's
private reporting policy, never a public issue containing exploit details.

## Verified configuration, 2026-09-05

All fourteen repositories returned HTTP 204 from the vulnerability-alert enabled
endpoint, and successful reads from the Dependabot alerts and dependency-graph
SBOM endpoints after alerts were enabled. GitHub documents that enabling alerts
also generates the dependency graph. The first SBOM snapshots contained only the
repository root; zero alerts were returned. This is configuration evidence, **not
proof that all dependencies were recognized or that no vulnerabilities exist**.

| Repository | Alerts enabled | Alerts readable | SBOM readable |
| --- | --- | --- | --- |
| akari | yes | yes | yes |
| hibana | yes | yes | yes |
| kagerou | yes | yes | yes |
| moji | yes | yes | yes |
| mojotui | yes | yes | yes |
| nagare | yes | yes | yes |
| nami | yes | yes | yes |
| nerai | yes | yes | yes |
| sen | yes | yes | yes |
| shuhafft | yes | yes | yes |
| yomi | yes | yes | yes |
| yuragi | yes | yes | yes |
| kumihan | yes | yes | yes |
| mojo-channel | yes | yes | yes |

A maintainer can repeat the read-only verification with authenticated `gh`:

```sh
for repository in akari hibana kagerou moji mojotui nagare nami nerai sen shuhafft yomi yuragi kumihan mojo-channel; do
  gh api --include "repos/Ameyanagi/$repository/vulnerability-alerts"
  gh api "repos/Ameyanagi/$repository/dependabot/alerts?per_page=100"
  gh api "repos/Ameyanagi/$repository/dependency-graph/sbom"
done
```

Do not commit alert bodies to public logs. Inspect private reports and vulnerable
versions through the repository Security interface.

## Coverage and the weekly review

GitHub's [supported ecosystem table](https://docs.github.com/en/code-security/reference/supply-chain-security/dependency-graph-supported-package-ecosystems)
is the authority for automatic recognition:

- GitHub recognizes Actions references in workflow `uses` fields, and version
  update PRs can maintain full SHA pins. GitHub explicitly states that **Actions
  vulnerability alerts require semantic version references, not SHA references**.
  Keep SHA pins; review upstream action advisories and release notes weekly and
  on every Dependabot PR. The tag comment identifies the release to review.
- Python dependencies in supported pip/Poetry manifests can be recognized.
  A `pyproject.toml` containing only formatter configuration does not expose
  Python tooling installed through Pixi, and shell `pixi exec --spec` commands
  are not pip manifests. Do not infer Python coverage from the filename alone.
- Pixi/Conda manifests, `pixi.lock`, Mojo compiler/library dependencies, and
  pre-commit hook dependencies are not covered by GitHub's listed automatic
  manifest analyzers. Their transitive contents need a separate review.

Each Monday and before a release, Ameyanagi reviews changed `pixi.lock` package
names, versions and channels, workflow `pixi exec` tool versions, and pre-commit
pins against upstream security advisories and release notices (Modular for Mojo,
Prefix for Pixi/Rattler, the relevant Python/tool projects and Conda package
maintainers). Use the GitHub Advisory Database for projects it covers, checking
package identity rather than assuming Conda names map to PyPI. Record the review
in the release/upgrade PR, including dependencies outside advisory coverage.
Unknown coverage is an explicit gap, never an empty result to dismiss.

The [GitHub alert documentation](https://docs.github.com/en/code-security/concepts/supply-chain-security/dependabot-alerts)
explains when the graph is generated and alerts are recalculated. Recheck the
SBOM after dependency changes; manually submitted dependency graphs may improve
inventory later, but do not automatically create advisory coverage for Mojo.
