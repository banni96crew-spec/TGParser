# Quality Gates

## Priorities

| Priority | Definition | Gate effect |
|---|---|---|
| P0 | Release impossible | Blocks all gates |
| P1 | Serious UX / brand / accessibility defect | Blocks release |
| P2 | Notable local defect | Fix or written waiver within 3 iterations |
| P3 | Optional improvement | Backlog; does not hold gate |

## Gates

| Gate | Name | Entry | Exit |
|---|---|---|---|
| G0 | Brief completeness | Input package | Every required brief field filled or `TBD + owner + deadline` |
| G1 | Strategy | Strategy + content plan + IA | Section jobs unique; one primary CTA; claims evidenced or marked hypothesis |
| G2 | Visual | Design direction | One concept; grid/type/color/image/motion principles; reference mapping |
| G3 | Design system | Design system + tokens + motion | Critical states; mobile/focus/reduced-motion rules |
| G4 | Implementation plan | File-level plan + route inventory | Scope frozen; Builder contract ready |
| G5 | Release | Production build + QA evidence | P0=0, P1=0; P2 closed/waived; commands green; evidence complete |

## Acceptance formula

`P0=0` AND `P1=0` AND every P2 closed or waivered AND declared lint/typecheck/tests/build green AND browser evidence complete.

Owner: Codex / QA Critic  
Do not duplicate P0–P3 definitions inside skills.
