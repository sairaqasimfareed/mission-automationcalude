"""
Google Flow External UI Automation, GF-2: persistent browser profile
management.

Everything under this package is provider-neutral browser-lifecycle
plumbing (profile directories, locking, a dedicated worker thread for
Playwright's Sync API) - it knows nothing about Google Flow's own UI.
The Flow-specific adapter (GF-4 onward) is a separate module that uses
this package, matching this initiative's own "browser selectors must
never become the application's business logic" boundary.
"""
