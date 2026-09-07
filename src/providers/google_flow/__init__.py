"""
The concrete Google Flow adapter (GF-4 onward).

Everything in this package knows real (or, until real-account
certification, fixture-verified) Google Flow UI structure - it is the
one place that knowledge is allowed to live, per this initiative's own
"centralize Flow UI knowledge inside the adapter" rule. Nothing outside
this package should ever import Playwright or reference a Flow
selector directly.
"""
