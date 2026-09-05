# pypdf remaining parser denial-of-service advisories

Candidate only, not activated. Advance pypdf 6.14.2 to 6.16.1, the minimum version covering CVE-2026-71852, CVE-2026-71870, CVE-2026-82398, CVE-2026-84309, CVE-2026-84310 and CVE-2026-84311. Runtime Python 3.11 requires no new dependency. Install the exact hash-locked wheel with --no-deps from each currently active image. Preserve every application module, including the known worker retrieval divergence.

The CID widths, ToUnicode, token-reading and XForm extraction paths are reachable via PdfReader/page.extract_text and PyPDFLoader. TreeObject.insert_child writing and bookmark extraction were not observed in the application callers; this is bounded source inspection, not a general unreachability proof. No production malicious PDF or ingestion is used to verify.

Verification before promotion: both isolated images must pass the existing 79 historical and 16 security tests, actual PDF text/table/crop, LangChain loader, image OCR and malformed/pixel fixtures, pip check, exact one-package delta, identical application module hashes and targeted vulnerability rescan. Production remains on the prior image until a separate reviewed rollout.
