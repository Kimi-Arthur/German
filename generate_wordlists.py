import pdfplumber
import json
import re

def normalize_char(c):
    c = c.lower()
    return {'ä': 'a', 'ö': 'o', 'ü': 'u'}.get(c, c)

def clean_word(w):
    w_lower = w.lower()
    for prefix in ["der ", "die ", "das ", "sich ", "(sich) "]:
        if w_lower.startswith(prefix):
            return w[len(prefix):].strip()
    return w.strip()

def should_skip_word(word):
    word_clean = word.strip()
    if len(word_clean) <= 1:
        return True
    if "_" in word_clean or re.match(r'^\d+$', word_clean):
        return True
    if word_clean.isupper():
        return True
    return False

def split_examples(examples_str):
    if not examples_str:
        return []
    text = re.sub(r'\s+', ' ', examples_str).strip()
    if re.search(r'^\d+\.', text) or re.search(r'\s+\d+\.', text):
        parts = re.split(r'\b\d+\.\s+', text)
        return [p.strip() for p in parts if p.strip()]
    else:
        return [s.strip() for s in re.split(r'(?<=[.!?])\s+(?=[A-Z])', text) if s.strip()]


def parse_word_details(raw_word):
    result = {
        "article": None,
        "headword": raw_word,
        "plural": None,
        "conjugation": [],
        "synonyms": [],
        "regional_usage": [],
        "variants": [],
        "female_form": None
    }
    
    work_str = raw_word.strip()
    
    # 1. Extract regional usage in parentheses first
    region_match = re.search(r'\s*\(([A-Z\s,]+)\)', work_str)
    if region_match:
        result["regional_usage"] = [x.strip() for x in region_match.group(1).split(",")]
        work_str = work_str[:region_match.start()].strip() + " " + work_str[region_match.end():].strip()
        work_str = work_str.strip()
        
    # 2. Extract synonyms/references indicated by → or ->
    ref_match = re.search(r'(?:[→\u2192]|->)\s*(.+)$', work_str)
    if ref_match:
        ref_text = ref_match.group(1).strip()
        syn_reg_match = re.match(r'^([A-Z\s,]+):\s*(.+)$', ref_text)
        if syn_reg_match:
            syn_reg = [x.strip() for x in syn_reg_match.group(1).split(",")]
            syn_val = syn_reg_match.group(2).strip()
            result["synonyms"].append({
                "word": syn_val,
                "regional_usage": syn_reg
            })
        else:
            result["synonyms"].append({
                "word": ref_text,
                "regional_usage": []
            })
        work_str = work_str[:ref_match.start()].strip()
        
    # 3. Check for plural only marker "(Pl.)"
    if "(Pl.)" in work_str or "(pl.)" in work_str:
        result["plural"] = "only plural"
        work_str = work_str.replace("(Pl.)", "").replace("(pl.)", "").strip()

    # 4. Check for female counterparts like "/ die Architektin, -nen"
    female_match = re.search(r'\/\s*(die\s+[A-ZÄÖÜ].+)', work_str)
    if female_match:
        female_raw = female_match.group(1).strip()
        result["female_form"] = parse_word_details(female_raw)
        work_str = work_str[:female_match.start()].strip()
        
    # 5. Extract articles (der, die, das, der/die, der/das)
    article_match = re.match(r'^(der/die/das|der/die|der/das|die/das|der|die|das)\b', work_str, re.IGNORECASE)
    if article_match:
        result["article"] = article_match.group(1).lower()
        work_str = work_str[article_match.end():].strip()
        
    # 6. Check for spelling variants inside headword
    variant_match = re.search(r'^([a-zA-ZäöüÄÖÜß-]+)\/\s*([a-zA-ZäöüÄÖÜß-]+)', work_str)
    if variant_match:
        result["variants"].append(variant_match.group(2))
        work_str = variant_match.group(1) + work_str[variant_match.end():]
        
    # 7. Split word and its inflections/plural
    parts = [p.strip() for p in work_str.split(",") if p.strip()]
    if parts:
        result["headword"] = parts[0]
        if result["article"]:
            if len(parts) > 1:
                result["plural"] = parts[1]
        else:
            if len(parts) > 1:
                result["conjugation"] = parts[1:]
                
    return result

def parse_column_words(column_words, word_max_x, pdf_type):
    # Group words by top coordinate with 4pt tolerance
    lines = {}
    for w in column_words:
        found = False
        for t in lines:
            if abs(t - w['top']) < 4.0:
                lines[t].append(w)
                found = True
                break
        if not found:
            lines[w['top']] = [w]
            
    # Sort lines by top coordinate
    sorted_tops = sorted(lines.keys())
    
    entries = []
    current_word = []
    current_examples = []
    prev_top = None
    pending_article = None
    
    for t in sorted_tops:
        line_words = sorted(lines[t], key=lambda x: x['x0'])
        
        # Split line_words into word part and example part
        word_part = [w for w in line_words if w['x0'] < word_max_x]
        example_part = [w for w in line_words if w['x0'] >= word_max_x]
        
        word_str = " ".join([w['text'] for w in word_part]).strip()
        example_str = " ".join([w['text'] for w in example_part]).strip()
        
        gap = (t - prev_top) if prev_top is not None else 0
        prev_top = t
        
        is_new_entry = False
        if word_str:
            if not current_word:
                is_new_entry = True
            else:
                word_lower = word_str.lower()
                is_aux = word_lower.startswith(("hat ", "ist ", "hat/ist ", "war ", "wurde ", "und "))
                starts_with_article = word_lower.startswith(("der ", "die ", "das ", "der/die ", "die/das ", "der/das ", "der/die/das "))
                # Check for structural indicators on the current line
                starts_with_arrow = word_str.startswith("→")
                starts_with_regional = word_str.startswith("(") and any(x in word_str[:6] for x in ["D", "A", "CH", "Sg.", "Pl.", "Sg", "Pl"])
                is_plural_marker = (word_str.startswith("-") or word_str.startswith("¨-") or word_str.lower() in ["(pl.)", "(sg.)"]) and len(word_str) <= 6
                is_gewesen = word_str.lower() == "gewesen"
                
                # Check for structural indicators from previous parsed word
                prev_word_str = current_word[-1].strip() if current_word else ""
                has_open_parenthesis = prev_word_str.count("(") > prev_word_str.count(")")
                
                base_word_str = current_word[0].strip() if current_word else ""
                is_reflexive = base_word_str.lower().startswith("sich ") or base_word_str.lower().startswith("(sich) ")
                
                if is_aux:
                    is_continuation = True
                elif is_gewesen:
                    is_continuation = True
                elif starts_with_arrow:
                    is_continuation = True
                elif starts_with_regional:
                    is_continuation = True
                elif is_plural_marker:
                    is_continuation = True
                elif has_open_parenthesis:
                    is_continuation = True
                elif starts_with_article:
                    is_continuation = False
                elif gap >= 13.0:
                    is_continuation = False
                else:
                    is_prefix_entry = prev_word_str.endswith("-") and " " not in prev_word_str
                    is_article = prev_word_str.lower() in ["der", "die", "das", "der/die", "die/das", "der/das", "der/die/das"]
                    is_reference = "→" in prev_word_str and (prev_word_str.endswith("→") or prev_word_str.endswith(":") or prev_word_str.endswith(";"))
                    
                    if is_prefix_entry:
                        is_continuation = False
                    elif is_article:
                        is_continuation = True
                    elif is_reference:
                        is_continuation = True
                    elif is_reflexive:
                        is_continuation = True
                    elif prev_word_str.endswith("-"):
                        is_continuation = True
                    else:
                        is_continuation = False
                
                is_new_entry = not is_continuation
                
        if is_new_entry:
            if current_word:
                word_full = " ".join(current_word).strip()
                pending_article = None
                for suffix in ["/der", "/die", "/das", "/ der", "/ die", "/ das"]:
                    if word_full.endswith(suffix):
                        pending_article = suffix.split("/")[-1].strip()
                        word_full = word_full[:-len(suffix)].strip()
                        break
                if word_full.endswith("/"):
                    word_full = word_full[:-1].strip()
                examples_full = " ".join(current_examples).strip()
                if should_skip_word(word_full):
                    pass
                elif len(word_full) > 1 or word_full.lower() not in "abcdefghijklmnopqrstuvwxyzäöüß":
                    entries.append({
                        "id": word_full.split(',')[0].strip(),
                        "raw_word": word_full,
                        "details": parse_word_details(word_full),
                        "examples": split_examples(examples_full)
                    })
            if pending_article and not word_str.lower().startswith(("der ", "die ", "das ")):
                word_str = pending_article + " " + word_str
            pending_article = None
            current_word = [word_str]
            current_examples = [example_str] if example_str else []
        else:
            if word_str:
                current_word.append(word_str)
            if example_str:
                current_examples.append(example_str)
            
    if current_word:
        word_full = " ".join(current_word).strip()
        for suffix in ["/der", "/die", "/das", "/ der", "/ die", "/ das", "/"]:
            if word_full.endswith(suffix):
                word_full = word_full[:-len(suffix)].strip()
                break
        examples_full = " ".join(current_examples).strip()
        if should_skip_word(word_full):
            pass
        elif len(word_full) > 1 or word_full.lower() not in "abcdefghijklmnopqrstuvwxyzäöüß":
            entries.append({
                "id": word_full.split(',')[0].strip(),
                "raw_word": word_full,
                "details": parse_word_details(word_full),
                "examples": split_examples(examples_full)
            })
            
    return entries

def parse_pdf_wordlist(filepath, start_page, end_page, pdf_type):
    print(f"Parsing {filepath} ({pdf_type}) from page {start_page} to {end_page}...")
    all_entries = []
    
    with pdfplumber.open(filepath) as pdf:
        for page_num in range(start_page, min(end_page + 1, len(pdf.pages) + 1)):
            page = pdf.pages[page_num - 1]
            words = page.extract_words()
            
            if pdf_type == "A1":
                content_words = [w for w in words if 80 <= w['top'] <= 780 and w['x0'] >= 100]
                left_words = content_words
                right_words = []
            else:
                content_words = [w for w in words if 80 <= w['top'] <= 780]
                left_words = [w for w in content_words if w['x0'] < 300]
                right_words = [w for w in content_words if w['x0'] >= 300]
                
            if pdf_type == "B1":
                left_word_max_x = 130
                right_word_max_x = 410
            elif pdf_type == "A2":
                left_word_max_x = 100
                right_word_max_x = 370
            else: # A1
                left_word_max_x = 235
                right_word_max_x = 999
                
            left_entries = parse_column_words(left_words, left_word_max_x, pdf_type)
            all_entries.extend(left_entries)
            
            if right_words:
                right_entries = parse_column_words(right_words, right_word_max_x, pdf_type)
                all_entries.extend(right_entries)
                
    return all_entries

def main():
    # A1 list
    a1_entries = parse_pdf_wordlist("A1_SD1_Wortliste_02.pdf", 9, 27, "A1")
    with open("A1_wortliste.json", "w", encoding="utf-8") as f:
        json.dump(a1_entries, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(a1_entries)} A1 entries to A1_wortliste.json")
    
    # A2 list
    a2_entries = parse_pdf_wordlist("Goethe-Zertifikat_A2_Wortliste.pdf", 8, 31, "A2")
    with open("A2_wortliste.json", "w", encoding="utf-8") as f:
        json.dump(a2_entries, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(a2_entries)} A2 entries to A2_wortliste.json")
    
    # B1 list
    b1_entries = parse_pdf_wordlist("Goethe-Zertifikat_B1_Wortliste.pdf", 16, 102, "B1")
    with open("B1_wortliste.json", "w", encoding="utf-8") as f:
        json.dump(b1_entries, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(b1_entries)} B1 entries to B1_wortliste.json")

if __name__ == "__main__":
    main()
