# Monorepo 초기 구조 생성 (pnpm)

## Planning
- [x] 환경 확인 (Node, Python, pnpm 버전)
- [x] 구현 계획 작성 + 사용자 리뷰 요청

## Execution
- [x] PROJECT_PLAN.md에 pnpm 패키지 매니저 명시
- [x] 루트 설정 파일 생성 (`package.json`, `pnpm-workspace.yaml`, `.npmrc`, `.gitignore`)
- [x] Next.js 앱 스캐폴딩 (`apps/web`)
- [x] FastAPI 스켈레톤 생성 (`apps/api`)
- [x] 공유 타입 패키지 생성 (`packages/shared`)
- [x] Docker Compose 구성 (Postgres + Redis)
- [x] Git commit & push

## Verification
- [x] pnpm install 정상 실행 (336 packages)
- [x] `@mathhub/shared` typecheck 통과
- [x] FastAPI import 성공
- [x] GitHub push 완료 (`be4fa7a`)
