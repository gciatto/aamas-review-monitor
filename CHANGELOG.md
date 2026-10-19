## 1.0.0 (2026-10-19)

### Features

* add deterministic review-process checks and SPC-grouped report ([6b3a9ab](https://github.com/gciatto/aamas-review-monitor/commit/6b3a9ab6d95d59751710d8e6f436f4cdb269ccd4))
* add paper detail screen to the TUI ([0829a9d](https://github.com/gciatto/aamas-review-monitor/commit/0829a9dba4b5898cd8ad20be90776b2b95684089))
* add read-only OpenReview collector of process metadata ([0114fc0](https://github.com/gciatto/aamas-review-monitor/commit/0114fc0fe84f186de4eeb1b36e70c7b7de7c46b1))
* add sync and report commands with local snapshots ([fa613e5](https://github.com/gciatto/aamas-review-monitor/commit/fa613e5ad6c29ab7f81a70f2fde9342541ab2b7a))
* add Textual TUI over the latest snapshot ([9db0db5](https://github.com/gciatto/aamas-review-monitor/commit/9db0db55a6f771520895964f672a3d615599eb0e))
* attachment dialog with path, OS actions, zip tree and cached PDF text ([674e9be](https://github.com/gciatto/aamas-review-monitor/commit/674e9bef54ba9e6987211e0c0ea1b846f8875c20))
* cache paper records and add show, issues, reviews, download and email commands ([ea2862c](https://github.com/gciatto/aamas-review-monitor/commit/ea2862c3682fa8d03f4a035691fe6a37041b34d7))
* CLI parity with the TUI: report --filter/--green, browse, attachment ([c794466](https://github.com/gciatto/aamas-review-monitor/commit/c79446645fbca32ff2765a6aaac09bf582e84824))
* configurable exponential backoff for OpenReview reads; bulk downloads survive failures ([09e5a6b](https://github.com/gciatto/aamas-review-monitor/commit/09e5a6b5734a884a0b65b67ccd0665ac611869cb))
* download, email, GREEN rows and colored details in the TUI ([c8018c5](https://github.com/gciatto/aamas-review-monitor/commit/c8018c52844b8b452cac8f6c02e804df506e748b))
* every TUI action in the command palette ([8ed971c](https://github.com/gciatto/aamas-review-monitor/commit/8ed971cac0463b625a90e2798a2e70973f1165ce))
* flag meta-review recommendations at odds with how the ratings rank ([f9c44b5](https://github.com/gciatto/aamas-review-monitor/commit/f9c44b5bb74fd07ae47f6f89b4ff5c6fd6650918))
* legend command and TUI legend dialog generated from check docstrings ([926bc3f](https://github.com/gciatto/aamas-review-monitor/commit/926bc3fa7c4a4e57ee2ab3d68e1b7eea086e94fd))
* list the checks each paper passes ([b64886d](https://github.com/gciatto/aamas-review-monitor/commit/b64886d0fb5591648674dbd234f739a555a3698d))
* more paper checks: milestones, late reviewers, recycled reviews, discussion, acknowledgements, SPC activity, meta-reviews ([7de5166](https://github.com/gciatto/aamas-review-monitor/commit/7de51665271b8bab636375125d2b43886f22e20b))
* on-request document checks of PDFs and supplementary material ([3f4f710](https://github.com/gciatto/aamas-review-monitor/commit/3f4f710b11c5dc59711f560269b1b1147a98b045))
* reuse the OpenReview session token across syncs ([2b1f3bd](https://github.com/gciatto/aamas-review-monitor/commit/2b1f3bdcbe71766af72421f5fecf620cdac3d83c))
* show bulk keys in the TUI footer next to their single-paper actions ([08a8a5d](https://github.com/gciatto/aamas-review-monitor/commit/08a8a5d77e9d6ba27acd274f22dc9c1ddceb140f))
* TUI icons and background jobs with progress, sign-in and SEND dialogs ([5557e1b](https://github.com/gciatto/aamas-review-monitor/commit/5557e1b1f32034a6588c33f2a59d1c05d00ecd8c))

### Bug Fixes

* legend shows milestones and similarity as percentages ([c95cc18](https://github.com/gciatto/aamas-review-monitor/commit/c95cc1811e18560c8e70b95db2b43d18af22cc8d))
* read pdffonts columns by header, so poppler-utils works like xpdf ([6a2eec8](https://github.com/gciatto/aamas-review-monitor/commit/6a2eec867d870ee94f22852ba62d0b917987cad0))
* read ratings from the AAMAS rating_proceedings field ([b7d2f2c](https://github.com/gciatto/aamas-review-monitor/commit/b7d2f2c1b6ab4c5da4d06c919bece6ac0f2e31e3))
* table actions no longer crash the TUI from the details screen ([75b3f13](https://github.com/gciatto/aamas-review-monitor/commit/75b3f139299505adfc3c61a2150f60849f6ceaaf))

### Documentation

* describe retries and backoff options ([b098289](https://github.com/gciatto/aamas-review-monitor/commit/b0982897246cec6f2b9886b458e92df2186b2aef))
* describe the attachment dialog and the f filter key ([46287ec](https://github.com/gciatto/aamas-review-monitor/commit/46287ec170be09f3d08016f07a00af9bd17e731a))
* describe the new TUI keys ([3d8eaf6](https://github.com/gciatto/aamas-review-monitor/commit/3d8eaf6294085352c495927452d83529d6d07666))
* describe the paper and document checks ([e687359](https://github.com/gciatto/aamas-review-monitor/commit/e687359f1dc67add39514d6cdfa6e136fcffa5e4))
* describe the TUI and its key bindings ([bbd3bd1](https://github.com/gciatto/aamas-review-monitor/commit/bbd3bd1b4ecc19e029d998051275e6cc6272e3c7))
* describe TUI icons, background jobs and dialogs ([059bb2c](https://github.com/gciatto/aamas-review-monitor/commit/059bb2c06b6c8f854ef8134065c44b32d9d7bfa9))
* document paper commands, cache and email safeguards ([7955cbc](https://github.com/gciatto/aamas-review-monitor/commit/7955cbc9969b40d25c2872df949a109987ca0aca))
* document the paper check convention and the legend ([a67c2e3](https://github.com/gciatto/aamas-review-monitor/commit/a67c2e3623b8a72a7e290ac0f03209c2cf0faab6))
* document usage, configuration and confidentiality boundaries ([1714f64](https://github.com/gciatto/aamas-review-monitor/commit/1714f64742489f69884ed50c837ca59c201bc496))
* point to the renamed aamas-review-monitor repository ([b340372](https://github.com/gciatto/aamas-review-monitor/commit/b340372904b152f539939f0814ab2732b1b7a45d))
* rewrite the README around features, checks and installation ([113d0f7](https://github.com/gciatto/aamas-review-monitor/commit/113d0f79a61feebd13a86cc3fec4f33392e52cdc))

### Tests

* block real OpenReview clients in every test ([7c1a7f2](https://github.com/gciatto/aamas-review-monitor/commit/7c1a7f2c75f62a41d039ec783b8632ee89da8ff6))
* fix Windows failures: OS-independent paths, wait for jobs started by dialog callbacks ([c074e9c](https://github.com/gciatto/aamas-review-monitor/commit/c074e9cb7451b0acfabe011228f9231306eeaedc))
* inspect downloads missing PDFs and supplementary zips, single and bulk ([9df1a8c](https://github.com/gciatto/aamas-review-monitor/commit/9df1a8ca4f6be97e216e9fcfc3910c847845fd54))
* make TUI attachment path assertion portable ([30dfbcb](https://github.com/gciatto/aamas-review-monitor/commit/30dfbcbf4818815ebab5415a4cad8226219f62d3))

### Build and continuous integration

* fall back to the workflow's own token when RELEASE_TOKEN is unset or empty ([0836f4e](https://github.com/gciatto/aamas-review-monitor/commit/0836f4eeca83dac5e44dbe88181e697ed003d86e))
* release to GitHub only and keep wheels as workflow artifacts ([dc255dd](https://github.com/gciatto/aamas-review-monitor/commit/dc255dde4185fa2f84b4dfde0fc537996d40bdf8))

### Refactoring

* expose paper metadata and reviews as structured fields ([1b04364](https://github.com/gciatto/aamas-review-monitor/commit/1b04364a71476c5f9fc938d858c077cf89a0b361))
* one documented function per paper check ([85fd214](https://github.com/gciatto/aamas-review-monitor/commit/85fd2148c36fd94d889fc9c61565eb13c1d62fb7))
* rename project to aamas-review-monitor ([71ca653](https://github.com/gciatto/aamas-review-monitor/commit/71ca6530a8605c36a02d89c91dcb815cfe29cfe4))
* separate token resume from login, report sync progress, split email into plan and send ([207cd89](https://github.com/gciatto/aamas-review-monitor/commit/207cd897620d8c00aa6f8d3f28d5a322d6a87f9b))

## [1.0.2](https://github.com/gciatto/aamas-review-monitor/compare/1.0.1...1.0.2) (2026-10-17)

### Bug Fixes

* **deps:** move poethepoet from runtime to dev dependencies ([2f1269d](https://github.com/gciatto/aamas-review-monitor/commit/2f1269da6cc7ae0ff0ae204f01ca4dd6d4becbb0))

## [1.0.1](https://github.com/gciatto/aamas-review-monitor/compare/1.0.0...1.0.1) (2026-10-16)

### Bug Fixes

* reject module names that are keywords, stdlib modules or existing paths ([0a4a765](https://github.com/gciatto/aamas-review-monitor/commit/0a4a76508a38508f7945170234404e952163f3f0))

### Build and continuous integration

* publish to PyPI before the release commit and tag, fail early on missing tokens ([413d0c4](https://github.com/gciatto/aamas-review-monitor/commit/413d0c4bbe1ac0c50c3589448b00ee044de18494))

## 1.0.0 (2026-10-16)

### Features

* expose __version__ from package metadata ([c3d220b](https://github.com/gciatto/aamas-review-monitor/commit/c3d220b25380486732489da7627d6c50077da596))
* flat layout with aamas_review_monitor at the root, resources, example module and subpackage ([01af6a4](https://github.com/gciatto/aamas-review-monitor/commit/01af6a479d41e7a5415900efa04479d22e901271))
* set the repository creator as project author on initialisation ([5c0d10c](https://github.com/gciatto/aamas-review-monitor/commit/5c0d10c10be940b4ac1488220f72d00ead6e3664))
* setup project with uv and pypi release ([fbb1f9c](https://github.com/gciatto/aamas-review-monitor/commit/fbb1f9cc1c1eb1acd9f74ae3ceaaba70dd1e0150))
* update commands for static checks and fixes, update matrix on CI using uv ([3d36460](https://github.com/gciatto/aamas-review-monitor/commit/3d3646082ba20876e5de452e75e7d94653857f7a))

### Dependency updates

* **deps:** update dependency uv_build to >=0.12.0,<0.13.0 ([#6](https://github.com/gciatto/aamas-review-monitor/issues/6)) ([ba751e1](https://github.com/gciatto/aamas-review-monitor/commit/ba751e1b5350b72f5d065848f2f32a44c075132f))
* **deps:** update dependency uv_build to >=0.13.0,<0.14.0 ([#10](https://github.com/gciatto/aamas-review-monitor/issues/10)) ([25b1c07](https://github.com/gciatto/aamas-review-monitor/commit/25b1c0779c76a494917459ba6f11331c08ae6d79))
* **deps:** update node.js to 24.16 ([#2](https://github.com/gciatto/aamas-review-monitor/issues/2)) ([ca30b5b](https://github.com/gciatto/aamas-review-monitor/commit/ca30b5be3de74d739acc1439a970373c1be975cc))
* **deps:** update node.js to 24.18 ([#3](https://github.com/gciatto/aamas-review-monitor/issues/3)) ([43389ad](https://github.com/gciatto/aamas-review-monitor/commit/43389adc8501d36685e6b2042446f2c50422e6e0))
* **deps:** update node.js to 24.19 ([#7](https://github.com/gciatto/aamas-review-monitor/issues/7)) ([3b5f8d8](https://github.com/gciatto/aamas-review-monitor/commit/3b5f8d8d3d35b965b22248f6409a459afd0cfe79))
* **deps:** update node.js to 24.20 ([#8](https://github.com/gciatto/aamas-review-monitor/issues/8)) ([be87e7e](https://github.com/gciatto/aamas-review-monitor/commit/be87e7ed54b94facdf66a8835f4ac34ee8dc7c5b))
* **deps:** update node.js to 24.21 ([#9](https://github.com/gciatto/aamas-review-monitor/issues/9)) ([926603b](https://github.com/gciatto/aamas-review-monitor/commit/926603bf8dcb2ba76af6cdadc1008b97c776c46b))
* **deps:** update node.js to 24.22 ([#11](https://github.com/gciatto/aamas-review-monitor/issues/11)) ([7f28ba8](https://github.com/gciatto/aamas-review-monitor/commit/7f28ba8b0d54c8cfa7248275ba3a562c1001c1d3))

### Bug Fixes

* add README, remove requirements, update project version ([aec4a09](https://github.com/gciatto/aamas-review-monitor/commit/aec4a095931fcf8a286d76746f2f93f4f999a7bd))
* **ci:** fix sed option ([601a215](https://github.com/gciatto/aamas-review-monitor/commit/601a21581c721da4468e6f6ce3ebe536e156206f))
* **ci:** install uv ([b5da10f](https://github.com/gciatto/aamas-review-monitor/commit/b5da10f5f2b387bfa6f95e66fb184454e262f497))
* **ci:** reset project version and changelog in init workflow ([a8b43a3](https://github.com/gciatto/aamas-review-monitor/commit/a8b43a36254e42999247b88171b3a75866348cc1))
* **ci:** update minimum python version on matrix ([6877625](https://github.com/gciatto/aamas-review-monitor/commit/68776252e9deb33873c18d27dd7aff570ec542ec))
* configure logging only when running the application ([601848a](https://github.com/gciatto/aamas-review-monitor/commit/601848af55f5b64241c02a8a73c3036be848f646))
* fix project name for realeasing on testpypi ([3a23fab](https://github.com/gciatto/aamas-review-monitor/commit/3a23fab9c9b797a9c060dda4a878ccc9ac8595dd))
* fix project name for realeasing on testpypi ([f7c9928](https://github.com/gciatto/aamas-review-monitor/commit/f7c9928a5a8ccffdacb210fda8d844a8dfb4e673))
* fix project version when releasing, remove bak files after renaming ([062d563](https://github.com/gciatto/aamas-review-monitor/commit/062d5634f7bec02ac16a927b4589f542d98515b0))
* fix release on test pypi ([b6a46a6](https://github.com/gciatto/aamas-review-monitor/commit/b6a46a67b8b6026aafc2c3927772c0d761a9c16a))
* fix rename in CI init workflow ([ca5ae97](https://github.com/gciatto/aamas-review-monitor/commit/ca5ae97145077ebc00b28c2ee69f9adc56d01b0e))
* fix rename script ([a583aa8](https://github.com/gciatto/aamas-review-monitor/commit/a583aa89bc03b0967148b218d0f9d93caf0592e2))
* fix rename script ([810b0bb](https://github.com/gciatto/aamas-review-monitor/commit/810b0bb7f539152fed805bef4eff986f7c03b788))
* fix token env var and add renovate ([0930407](https://github.com/gciatto/aamas-review-monitor/commit/09304071b04da565c3fdc112a4a24b25115ed749))
* make checkout before uv sync ([3482685](https://github.com/gciatto/aamas-review-monitor/commit/3482685f6b216bbbda74620389c89539dc5e562a))
* make rename-template.sh portable and robust to any valid project name ([297fe29](https://github.com/gciatto/aamas-review-monitor/commit/297fe2917b983aebf386716f927c16f0c12f0c95))
* name the project after the repository ([5db3a8e](https://github.com/gciatto/aamas-review-monitor/commit/5db3a8e88957079dce22dc02f066c9564ff7956b))
* rename test directory, fixing rename script ([cfd46b7](https://github.com/gciatto/aamas-review-monitor/commit/cfd46b7d3fce8b4f69469b1c51f51cbf4c55501b))

### Documentation

* add AGENTS.md with contributor and agent conventions ([1d89152](https://github.com/gciatto/aamas-review-monitor/commit/1d89152d03b4602dbfd6b62be818826c9079461c))
* describe the new layout and the resources and naming conventions ([1e9976f](https://github.com/gciatto/aamas-review-monitor/commit/1e9976ff6d02ada8feec7a9a8a7ddb31f6478c43))
* explain lint vs format tasks and when to install each git hook ([63843c2](https://github.com/gciatto/aamas-review-monitor/commit/63843c2262473c6420064c25174d9afc4676c154))
* mention that forks are not initialised ([4975008](https://github.com/gciatto/aamas-review-monitor/commit/49750087688b876c4ba21b23f2959ebfa076c65f))

### Build and continuous integration

* **deps:** update actions/checkout action to v7 ([#4](https://github.com/gciatto/aamas-review-monitor/issues/4)) ([0fc5e6a](https://github.com/gciatto/aamas-review-monitor/commit/0fc5e6adb5d53dc0a579f6ffaa1d426a4ed31aa8))
* **deps:** update actions/setup-node action to v7 ([#5](https://github.com/gciatto/aamas-review-monitor/issues/5)) ([3a6a565](https://github.com/gciatto/aamas-review-monitor/commit/3a6a565d3f302526af89890c72a0d73820e76995))
* install uv with astral-sh/setup-uv and cache it ([5e15439](https://github.com/gciatto/aamas-review-monitor/commit/5e15439d34747df57ac2b7b591de8eba3fe16d63))
* skip template initialisation in forks ([c2a8281](https://github.com/gciatto/aamas-review-monitor/commit/c2a828158365e9eea6246beacf9110e0b1dba43f))
* upload only wheels and sdists as release assets ([ace6af8](https://github.com/gciatto/aamas-review-monitor/commit/ace6af82f9dc0fae8d011e7391eff6adce689543))

### General maintenance

* add poe tasks to install and uninstall local git hooks ([c449d6d](https://github.com/gciatto/aamas-review-monitor/commit/c449d6d06b28372624754e865ac32a7c74398419))
* make gciatto the default renovate assignee ([5fdc7af](https://github.com/gciatto/aamas-review-monitor/commit/5fdc7af709df564858a7a719451eb398d09d0e76))
* make Giovanni Ciatto the template author ([13828ef](https://github.com/gciatto/aamas-review-monitor/commit/13828effd92414843187bebd4d962d249d2b27cb))
* **release:** 1.0.0 [skip ci] ([c329176](https://github.com/gciatto/aamas-review-monitor/commit/c329176c515ef3bc14987d071ee905dda097d892))
* **release:** 1.0.1 [skip ci] ([bb796b8](https://github.com/gciatto/aamas-review-monitor/commit/bb796b819cce145b6dba692806cbaf83645c7ea8))
* **release:** 1.0.2 [skip ci] ([4e3f43c](https://github.com/gciatto/aamas-review-monitor/commit/4e3f43ce3930bf0e051fe8fdd18917e10de7cb6e))
* **release:** 1.0.3 [skip ci] ([7819a43](https://github.com/gciatto/aamas-review-monitor/commit/7819a43315010eae077dd4353a2cfcfb258a0c5d))
* **release:** 1.0.4 [skip ci] ([d890904](https://github.com/gciatto/aamas-review-monitor/commit/d890904dd17f45c92c75a3b269919873fd1b45a0))
* **release:** 1.0.5 [skip ci] ([d9777f5](https://github.com/gciatto/aamas-review-monitor/commit/d9777f5abe0e933b2cea4cb309231f4ad2b9a148))
* **release:** 1.0.6 [skip ci] ([3643841](https://github.com/gciatto/aamas-review-monitor/commit/364384182e06f863b1d083dbd67938f6b7ce3c81))
* **release:** 1.0.7 [skip ci] ([49535fe](https://github.com/gciatto/aamas-review-monitor/commit/49535fed5348a65b71459a526e1a7ea3298a8a75))
* **release:** 1.1.0 [skip ci] ([0583291](https://github.com/gciatto/aamas-review-monitor/commit/058329156b53599e9fd71ca5e4bad52706722d30))
* **release:** 1.1.1 [skip ci] ([505f3df](https://github.com/gciatto/aamas-review-monitor/commit/505f3dfd0ca8058ef7d91dd74d0944da731b81f2))
* **release:** 1.1.2 [skip ci] ([7efaf3b](https://github.com/gciatto/aamas-review-monitor/commit/7efaf3b7594a7f873c09bd436e79a0ba527f159e))
* **release:** 1.1.3 [skip ci] ([231da23](https://github.com/gciatto/aamas-review-monitor/commit/231da2341107acbbc5561e6775612b455695c6f0))
* **release:** 1.1.4 [skip ci] ([08169f4](https://github.com/gciatto/aamas-review-monitor/commit/08169f46dbab13dbd1e71f849e298e7cb5b34fb6))
* setup repo ([dea32e9](https://github.com/gciatto/aamas-review-monitor/commit/dea32e9bbd82d3797c8576e68f7eae1d831f3a32))
* update .gitignore ([232253c](https://github.com/gciatto/aamas-review-monitor/commit/232253cbeb7d784db379255ebf6821a8393298b5))
* update README ([2fe3e45](https://github.com/gciatto/aamas-review-monitor/commit/2fe3e45f4f35d4ee0cf102e605f909e4899c574a))

### Refactoring

* rework rename-template script ([ce15366](https://github.com/gciatto/aamas-review-monitor/commit/ce15366a18e10cd5facccfcb71e5c4f6b0a7abf8))
* update application entry point ([7d51c49](https://github.com/gciatto/aamas-review-monitor/commit/7d51c496596af05d2ab59437b3893c2668b950f5))

## [1.1.4](https://github.com/Mala1180/uv-python-project-template/compare/1.1.3...1.1.4) (2026-05-13)

### Bug Fixes

* **ci:** install uv ([b5da10f](https://github.com/Mala1180/uv-python-project-template/commit/b5da10f5f2b387bfa6f95e66fb184454e262f497))

## [1.1.3](https://github.com/Mala1180/uv-python-project-template/compare/1.1.2...1.1.3) (2026-05-13)

### Bug Fixes

* **ci:** fix sed option ([601a215](https://github.com/Mala1180/uv-python-project-template/commit/601a21581c721da4468e6f6ce3ebe536e156206f))

## [1.1.2](https://github.com/Mala1180/uv-python-project-template/compare/1.1.1...1.1.2) (2026-05-13)

### Bug Fixes

* **ci:** reset project version and changelog in init workflow ([a8b43a3](https://github.com/Mala1180/uv-python-project-template/commit/a8b43a36254e42999247b88171b3a75866348cc1))

## [1.1.1](https://github.com/Mala1180/uv-python-project-template/compare/1.1.0...1.1.1) (2026-05-13)

### Bug Fixes

* **ci:** update minimum python version on matrix ([6877625](https://github.com/Mala1180/uv-python-project-template/commit/68776252e9deb33873c18d27dd7aff570ec542ec))
* make checkout before uv sync ([3482685](https://github.com/Mala1180/uv-python-project-template/commit/3482685f6b216bbbda74620389c89539dc5e562a))

## [1.1.0](https://github.com/Mala1180/uv-python-project-template/compare/1.0.7...1.1.0) (2026-05-13)

### Features

* update commands for static checks and fixes, update matrix on CI using uv ([3d36460](https://github.com/Mala1180/uv-python-project-template/commit/3d3646082ba20876e5de452e75e7d94653857f7a))

## [1.0.7](https://github.com/Mala1180/uv-python-project-template/compare/1.0.6...1.0.7) (2026-05-13)

### Bug Fixes

* fix rename in CI init workflow ([ca5ae97](https://github.com/Mala1180/uv-python-project-template/commit/ca5ae97145077ebc00b28c2ee69f9adc56d01b0e))

## [1.0.6](https://github.com/Mala1180/uv-python-project-template/compare/1.0.5...1.0.6) (2026-05-13)

### Bug Fixes

* fix rename script ([a583aa8](https://github.com/Mala1180/uv-python-project-template/commit/a583aa89bc03b0967148b218d0f9d93caf0592e2))
* fix rename script ([810b0bb](https://github.com/Mala1180/uv-python-project-template/commit/810b0bb7f539152fed805bef4eff986f7c03b788))
* rename test directory, fixing rename script ([cfd46b7](https://github.com/Mala1180/uv-python-project-template/commit/cfd46b7d3fce8b4f69469b1c51f51cbf4c55501b))

## [1.0.5](https://github.com/Mala1180/uv-python-project-template/compare/1.0.4...1.0.5) (2026-05-12)

### Bug Fixes

* fix project version when releasing, remove bak files after renaming ([062d563](https://github.com/Mala1180/uv-python-project-template/commit/062d5634f7bec02ac16a927b4589f542d98515b0))

### General maintenance

* update README ([2fe3e45](https://github.com/Mala1180/uv-python-project-template/commit/2fe3e45f4f35d4ee0cf102e605f909e4899c574a))

### Refactoring

* rework rename-template script ([ce15366](https://github.com/Mala1180/uv-python-project-template/commit/ce15366a18e10cd5facccfcb71e5c4f6b0a7abf8))

## [1.0.4](https://github.com/Mala1180/uv-python-project-template/compare/1.0.3...1.0.4) (2026-05-12)

### Bug Fixes

* fix project name for realeasing on testpypi ([3a23fab](https://github.com/Mala1180/uv-python-project-template/commit/3a23fab9c9b797a9c060dda4a878ccc9ac8595dd))
* fix project name for realeasing on testpypi ([f7c9928](https://github.com/Mala1180/uv-python-project-template/commit/f7c9928a5a8ccffdacb210fda8d844a8dfb4e673))

## [1.0.3](https://github.com/Mala1180/uv-python-project-template/compare/1.0.2...1.0.3) (2026-05-12)

### Bug Fixes

* add README, remove requirements, update project version ([aec4a09](https://github.com/Mala1180/uv-python-project-template/commit/aec4a095931fcf8a286d76746f2f93f4f999a7bd))

## [1.0.2](https://github.com/Mala1180/uv-python-project-template/compare/1.0.1...1.0.2) (2026-05-12)

### Bug Fixes

* fix token env var and add renovate ([0930407](https://github.com/Mala1180/uv-python-project-template/commit/09304071b04da565c3fdc112a4a24b25115ed749))

## [1.0.1](https://github.com/Mala1180/uv-python-project-template/compare/1.0.0...1.0.1) (2026-05-12)

### Bug Fixes

* fix release on test pypi ([b6a46a6](https://github.com/Mala1180/uv-python-project-template/commit/b6a46a67b8b6026aafc2c3927772c0d761a9c16a))

## 1.0.0 (2026-05-12)

### Features

* setup project with uv and pypi release ([fbb1f9c](https://github.com/Mala1180/uv-python-project-template/commit/fbb1f9cc1c1eb1acd9f74ae3ceaaba70dd1e0150))

### General maintenance

* setup repo ([dea32e9](https://github.com/Mala1180/uv-python-project-template/commit/dea32e9bbd82d3797c8576e68f7eae1d831f3a32))
