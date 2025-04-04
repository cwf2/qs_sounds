'''init.py - generate data for Quintus app

This script downloads the text of Quintus and splits it
into individual sounds per line so that we can tally
things like alliteration and assonance.
'''

#
# import statements
#

# utils
import os
import re
import json
from lxml import etree
import requests
import unicodedata as ud

# DICES
from dicesapi import DicesAPI

# for analysis
import pandas as pd
import numpy as np

#
# global values
#

CTS_ENDPOINT = "https://scaife.perseus.org/library/{urn}/cts-api-xml/"
NSMAP = {
    "cts": "http://chs.harvard.edu/xmlns/cts",
    "tei": "http://www.tei-c.org/ns/1.0"
}
SOUNDS_FILE = os.path.join("data", "sounds.csv")

# permanent changes
one_time = {
    "ς": "σ",
    "θ": "τ",
    "χ": "κ",
    "φ": "π",
}

# swaps that are just for counting purposes
reversible = {
   "οι": "O",
    "αι": "Ι",
    "ει": "e",
    "υι": "Y",
    "αυ": "Α",
    "ευ": "u",
    "ου": "U",
}

# map the reversible replacements back to their original spellings
reverse_replacements = dict()
for k, v in reversible.items():
    reverse_replacements[v] = k

# combine the two types of replacements into a single dictionary
replacements = dict()
for k, v in reversible.items():
    replacements[k] = v
for k, v in one_time.items():
    replacements[k] = v



#
# function definitions
#

# extract loci and verse lines
def create_id(book, line):
    '''Create a string to represent locus
        - zero pad book number to 2 digits
        - zero pad line number to 3 digits
        - keep letter suffix
        - use underscore to separate book and line
    '''

    # check line for alpha suffix
    m = re.match(r"(\d+)([a-z])", line)
    if m:
        numeric = m.group(1)
        letter = m.group(2)
    else:
        numeric = line
        letter = ""

    id = f"{int(book):02d}_{int(numeric):03d}{letter}"

    return id
    
# download text from Perseus
def retrieve_text(urn):
    '''Download a text from Scaife's CTS endpoint'''
    
    # get TEI XML from remote CTS
    url = CTS_ENDPOINT.format(urn=urn)
    res = requests.get(url)
    
    if not res.ok:
        res.raise_for_status()
    
    xml = etree.fromstring(res.content)
    
    # empty list to hold the lines
    lines = list()

    # iterate over books
    for book in xml.findall('.//tei:div[@subtype="book"]', namespaces=NSMAP):
        bn = book.get('n')

        # remove notes
        for note in book.findall('.//tei:l//tei:note', namespaces=NSMAP):
            note.clear(keep_tail=True)

        # extract lines
        for line in book.findall('.//tei:l', namespaces=NSMAP):

            ln = line.get('n')
            if not ln:
                continue

            text = ''.join(line.itertext())
            text = re.sub(r'\s+', ' ', text).strip()

            line_id = create_id(bn, ln)

            # add to array
            lines.append(dict(
                id = line_id,
                book = bn,
                line = ln,
                text = text,
            ))

    # convert to data frame
    lines = pd.DataFrame(lines)
    
    return lines


# extract sounds from text
def sounds_per_word(word):
    '''return a dictionary:
        - each item represents one Greek word
        - keys are sounds
        - values are counts'''
    
    # suppress non string input (FIXME)
    if not isinstance(word, str):
        word = ""

    # take apart accents and vowels
    decomposed_text = ud.normalize("NFKD", word)

    # lowercase everything
    decomposed_text = decomposed_text.lower().strip()

    # extract rough breathing
    breathing = "h" if "\u0314" in decomposed_text else ""

    # remove diacritics
    decomposed_text = breathing + re.sub("[^α-ω ]", "", decomposed_text).strip()

    # replace complex sounds with single characters
    for k, v in replacements.items():
        decomposed_text = re.sub(k, v, decomposed_text)

    # check for empty string
    if not decomposed_text:
        return dict()

    # initialize count
    count = dict()

    # record initial letter for alliteration
    first_letter = decomposed_text[0]
    count["_" + reverse_replacements.get(first_letter, first_letter)] = 1

    # now increment count for remaining letters
    for char in decomposed_text:
        key = reverse_replacements.get(char, char)

        # increment the count for that character
        count[key] = count.get(key, 0) + 1

    return count
    

#
# main
#

if __name__ == "__main__":

    # get QS data
    lines = retrieve_text("urn:cts:greekLit:tlg2046.tlg001.perseus-grc2")
    
    #  connection to DICES
    api = DicesAPI(
        logfile = 'dices.log',
        logdetail = 0,
    )
    
    # request all speeches by Quintus
    speeches = api.getSpeeches(author_name="Quintus")
    
    # default label is narration
    lines["label"] = "narration"
    
    # label speeches
    for s in speeches:
        book_first, line_first = s.l_fi.split(".")
        book_last, line_last = s.l_la.split(".")

        id_first = create_id(book_first, line_first)
        id_last = create_id(book_last, line_last)

        lines.loc[lines["id"].between(id_first, id_last), "label"] = "speech"
    
    # get sounds for each line
    words = pd.DataFrame(dict(
        id = lines["id"],
        book = lines["book"],
        line = lines["line"],
        label = lines["label"],
        word = lines["text"].str.split(),
    )).explode("word")
    words = words.reset_index(drop=True)
    
    print(words)
    
    words["sound"] = words["word"].apply(sounds_per_word)
    
    sounds = pd.DataFrame(words["sound"].tolist()).fillna(0).astype(int)
    sounds = sounds[sorted(sounds.columns)]
    sounds = pd.concat([words[["id", "book", "line", "label", "word"]], sounds], axis=1)
    
    # write to file
    sounds.to_csv(SOUNDS_FILE, index=False)    
    
    