"""
extraction.py – What the extraction stage says to the model outside its
prompts, in English.

A profile that extends this one and names an extraction spec of its own
(`SPEC_PATH`) gets these sentences with the prompts beside this file. See
docpipe/extraction/wording.py for what each name is filled with.

Author: Felix Vossel
"""

# How the documents write the decimal is the rule `decimal_mark` (rules.json
# beside this file).

# The language tag of the ontology's alternative labels that a vocabulary
# snapshot keeps for this profile, the words its spec is held against. This
# profile has no snapshot of its own; one that extends it and builds one reads
# the tag here.
ALT_LABEL_LANGUAGE = "en"

# The language of the core's contract text in this profile's prompts: the
# parts files beside this file that name a template (`template: rows`) are put
# together with the template of this language. A profile that extends this one
# and keeps those files gets it with them; one that writes parts files of its
# own declares the language they are in.
CONTRACT_LANGUAGE = "en"


# What the preflight (`docpipe preflight`) holds this profile's prompts to,
# beyond the keys the stage reads by name: a wording the run depends on. The
# prompts are in the profile's language, so the passage is too. A profile
# that words a prompt of its own says its own passages.
# (what is checked, prompt, passage, True: has to be there, False: must not)
PROMPT_CHECKS = ()

# What the stage says to the model outside its prompts (why an answer was not
# taken, what was wrong with a reply) is a file beside them:
# prompts/extraction/phrases.json (docpipe/phrases.py).
