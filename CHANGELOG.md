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
