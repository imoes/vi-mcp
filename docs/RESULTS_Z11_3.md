# Z11-3 results: a larger forget-by-document test (E1)

Status: **running**. Pre-registration: [PREREG_Z11_3.md](PREREG_Z11_3.md), sha256 0ec74f07…, frozen 23.11.2026 13:20:08 UTC
before any question was written. All times are UTC from `date -u`.

## Diary

- **13:19:54.** First freeze, sha256 a3ceffc0…, commit 7e9ffee.
- **13:20:08. Re-frozen, sha256 0ec74f07…, commit 522e4d4.**
  - **Correction.** The heading of the literature section had stated a reading time of "13:2x–13:4x UTC". That was a guess,
    and it lay in the future. The reading ended before 13:19 UTC.
  - Only that line changed. The old commit was amended before any Z11-3 question or answer existed, so no data saw either
    version.
- **13:20.** The chain was started on the CPU workstation. It waits until 16:00 UTC before the first writer request.
- Writer file check: the served file is 22,853,663,008 bytes. Amendment 1 gives that size for the file run 3 used.
- **16:00:16.** The writer started as a client with 2 workers. The guard probes the server's health every 60 s. Every probe so far
  answered in 0.01 s, and the server's restart count and start time have not changed. At 16:10:25, after 175 of 500 documents in
  pass 1, 86 questions had been kept.
