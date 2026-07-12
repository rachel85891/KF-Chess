"""Optional extras track (spec.md §2's "additional optional future
movement rules"): JUMP and Promotion. Deliberately kept separate from
every core package (model/, rules/, realtime/, engine/, input/, io/,
view/, texttests/) so the core can always be proven to still satisfy
spec.md §13's "exactly 4 commands" with this package simply absent -
nothing under kungfu_chess/extra/ is imported by any core module.
"""
