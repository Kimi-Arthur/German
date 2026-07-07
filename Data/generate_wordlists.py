import pdfplumber
import json
import re

def normalize_char(c):
    c = c.lower()
    return {'ä': 'a', 'ö': 'o', 'ü': 'u'}.get(c, c)

def clean_word_spaces(text):
    return re.sub(r'\b(der|die|das|der/die|die/das|der/das)([A-ZÄÖÜ])', r'\1 \2', text)

def clean_empty_fields(d):
    if not d:
        return {}
    cleaned = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, list) and len(v) == 0:
            continue
        if isinstance(v, dict):
            v_clean = clean_empty_fields(v)
            if v_clean:
                cleaned[k] = v_clean
            continue
        cleaned[k] = v
    return cleaned

def clean_entry_dict(entry):
    cleaned = {
        "id": entry["id"],
        "raw_word": entry["raw_word"]
    }
    details_clean = clean_empty_fields(entry["details"])
    if details_clean:
        cleaned["details"] = details_clean
    if entry["examples"]:
        cleaned["examples"] = entry["examples"]
    return cleaned

def clean_word(w):
    w_lower = w.lower()
    for prefix in ["der ", "die ", "das ", "sich ", "(sich) "]:
        if w_lower.startswith(prefix):
            return w[len(prefix):].strip()
    return w.strip()

def get_clean_id(word):
    clean = word.strip()
    # 1. Strip references starting with arrow (→ or ->)
    clean = re.sub(r'\s*(?:[→\u2192]|->).*$', '', clean).strip()
    # 2. Strip regional markers in parentheses like (D, A) or (CH) (allowing corrupted digits/periods inside)
    clean = re.sub(r'\s*\([A-Z\d\s,.]+\)\s*', ' ', clean).strip()
    # 3. Strip Pl/Sg markers
    clean = re.sub(r'\s*\(([Pp]l\.|[Ss]g\.)\)\s*', ' ', clean).strip()
    # 4. Now split by comma (since commas inside parentheses are already stripped)
    clean = clean.split(',')[0].strip()
    
    # 5. Split slash-separated variants
    # E.g. die Rezeption/Reception -> die Rezeption
    parts = clean.split()
    if parts:
        articles = ["der", "die", "das", "der/die", "die/das", "der/das", "das/der", "der/die/das"]
        article_part = ""
        headword_part = clean
        if parts[0].lower() in articles:
            article_part = parts[0]
            headword_part = " ".join(parts[1:])
            
        # Rules to split the headword:
        # 1. No spaces in headword_part (single word/phrase)
        # 2. Exactly one slash in headword_part
        # 3. No parentheses in headword_part
        if (
            " " not in headword_part and 
            headword_part.count("/") == 1 and 
            "(" not in headword_part and 
            ")" not in headword_part
        ):
            left, right = headword_part.split("/")
            if left and right and not left.endswith("-") and not right.startswith("-") and not right.endswith("-") and not left.startswith("-"):
                headword_part = left
                
        if article_part:
            clean = f"{article_part} {headword_part}".strip()
        else:
            clean = headword_part.strip()
            
    # Clean up double spaces
    clean = re.sub(r'\s+', ' ', clean)
    clean = clean.rstrip(";, ")
    return clean

def join_word_parts(parts):
    if not parts:
        return ""
    result = parts[0]
    articles = {"der", "die", "das", "der/die", "die/das", "der/das", "der/die/das"}
    for p in parts[1:]:
        p_clean = p.strip()
        if not p_clean:
            continue
        result_last = result.split()[-1].lower().rstrip("/;,") if result.split() else ""
        if result.endswith("-") and not result.endswith(" -") and not result.endswith(",-") and not result.endswith(", -"):
            result = result[:-1] + p_clean
        elif p_clean.startswith("die ") and "der " in result.lower():
            result = result + " / " + p_clean
        elif result_last in articles:
            result = result + " " + p_clean
        elif p_clean[0].islower():
            result = result + " " + p_clean
        elif p_clean.startswith(",") or p_clean.startswith("-") or p_clean.startswith("("):
            result = result + " " + p_clean
        elif result.endswith("/"):
            result = result + p_clean
        elif result.endswith((",", ":", "→", "->")):
            result = result + " " + p_clean
        elif p_clean.startswith(("gehen/sein", "werden/sein", "haben/sein", "sein", "haben")):
            result = result + " " + p_clean
        else:
            result = result + "; " + p_clean
    return result.strip()

def join_example_lines(lines):
    if not lines:
        return ""
    result = lines[0]
    for l in lines[1:]:
        if result.endswith("-"):
            result = result[:-1] + l
        else:
            result = result + "\n" + l
    return result.strip()

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
    # If it has numbered examples (like "1. ... 2. ...")
    if re.search(r'^\d+\.', examples_str) or re.search(r'\s+\d+\.', examples_str):
        parts = re.split(r'\b\d+\.\s+', examples_str)
        return [p.replace("\n", " ").strip() for p in parts if p.strip()]
    else:
        # Split on sentence boundaries at newlines (which indicates logical paragraph break)
        parts = re.split(r'(?<=[.!?])\s*\n\s*(?=[A-ZÄÖÜ])', examples_str)
        cleaned_parts = []
        for p in parts:
            p_clean = p.replace("\n", " ").strip()
            p_clean = re.sub(r'\s+', ' ', p_clean)
            if p_clean:
                cleaned_parts.append(p_clean)
        return cleaned_parts


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
    
    # 1. Extract regional usage in parentheses first (allowing corrupted digits/periods inside)
    region_match = re.search(r'\s*\(([A-Z\d\s,.]+)\)', work_str)
    if region_match:
        raw_regions = region_match.group(1).split(",")
        clean_regions = []
        for r in raw_regions:
            r_clean = re.sub(r'[\d.]', '', r).strip()
            if r_clean in ["D", "A", "CH"]:
                clean_regions.append(r_clean)
        result["regional_usage"] = clean_regions
        work_str = work_str[:region_match.start()].strip() + " " + work_str[region_match.end():].strip()
        work_str = work_str.strip()
        
    # 2. Extract synonyms/references indicated by → or ->
    ref_match = re.search(r'(?:[→\u2192]|->)\s*(.+)$', work_str)
    if ref_match:
        ref_text = ref_match.group(1).strip()
        
        # Segment ref_text by regional prefixes
        prefix_pattern = r'\b((?:CH|D|A)(?:\s*,\s*(?:CH|D|A))*)\s*:'
        matches = list(re.finditer(prefix_pattern, ref_text))
        
        chunks = []
        if not matches:
            chunks.append((ref_text, []))
        else:
            if matches[0].start() > 0:
                pre_text = ref_text[:matches[0].start()].strip()
                if pre_text:
                    chunks.append((pre_text, []))
            
            for idx, match in enumerate(matches):
                start_idx = match.end()
                end_idx = matches[idx + 1].start() if idx + 1 < len(matches) else len(ref_text)
                chunk_text = ref_text[start_idx:end_idx].strip()
                
                raw_regs = match.group(1).split(",")
                chunk_regs = []
                for r in raw_regs:
                    r_clean = r.strip()
                    if r_clean in ["D", "A", "CH"]:
                        chunk_regs.append(r_clean)
                chunks.append((chunk_text, chunk_regs))
                
        active_regs = []
        for chunk_text, chunk_regs in chunks:
            if chunk_regs:
                active_regs = chunk_regs
            syn_parts = [p.strip() for p in chunk_text.split(";") if p.strip()]
            for part in syn_parts:
                part = part.strip().strip(",").strip()
                if not part:
                    continue
                
                syn_reg = list(active_regs)
                suffix_match = re.search(r'\s*\(([A-Z\d\s,.]+)\)$', part)
                if suffix_match:
                    raw_regs = suffix_match.group(1).split(",")
                    syn_reg = []
                    for r in raw_regs:
                        r_clean = re.sub(r'[\d.]', '', r).strip()
                        if r_clean in ["D", "A", "CH"]:
                            syn_reg.append(r_clean)
                    part = part[:suffix_match.start()].strip()
                    
                prefix_match = re.match(r'^([A-Z\s,]+):\s*(.+)$', part)
                if prefix_match:
                    prefix_regs = [x.strip() for x in prefix_match.group(1).split(",")]
                    syn_reg = []
                    for r in prefix_regs:
                        if r in ["D", "A", "CH"]:
                            syn_reg.append(r)
                    part = prefix_match.group(2).strip()
                    
                clean_part_for_check = clean_word_spaces(part)
                is_female = clean_part_for_check.startswith("die ") and clean_part_for_check.split(',')[0].strip().endswith("in")
                
                part_clean = part.split(',')[0].strip()
                part_clean = re.sub(r'\s*(?:[→\u2192]|->).*$', '', part_clean).strip()
                
                if is_female:
                    fem_details = parse_word_details(clean_part_for_check)
                    if syn_reg:
                        fem_details["regional_usage"] = sorted(list(set(syn_reg)))
                    result["female_form"] = {
                        "id": get_clean_id(clean_part_for_check),
                        "raw_word": clean_part_for_check,
                        "details": fem_details
                    }
                else:
                    result["synonyms"].append({
                        "word": part_clean,
                        "regional_usage": sorted(list(set(syn_reg)))
                    })
        work_str = work_str[:ref_match.start()].strip().rstrip(";,")
        
    # 3. Check for plural only marker "(Pl.)" and singular only marker "(Sg.)"
    if re.search(r'\([Pp]l\.\)', work_str):
        result["plural"] = "(Pl.)"
        work_str = re.sub(r'\s*\([Pp]l\.\)\s*', ' ', work_str).strip()
    elif re.search(r'\([Ss]g\.\)', work_str):
        result["plural"] = "(Sg.)"
        work_str = re.sub(r'\s*\([Ss]g\.\)\s*', ' ', work_str).strip()

    # 4. Check for female counterparts like "/ die Architektin, -nen" or ", die Wissenschaftlerin, -nen"
    female_match = re.search(r'(?:\/|,)\s*(die\s+[A-ZÄÖÜ][a-zA-ZäöüßÄÖÜ]+(?:\s*,\s*-\w+)?)', work_str)
    if female_match:
        female_raw = female_match.group(1).strip()
        result["female_form"] = {
            "id": get_clean_id(female_raw),
            "raw_word": female_raw,
            "details": parse_word_details(female_raw)
        }
        work_str = work_str[:female_match.start()].strip()
        
    # 5. Extract articles (der, die, das, der/die, der/das, etc.)
    article_match = re.match(r'^((?:der|die|das)(?:\/(?:der|die|das))*)\b', work_str, re.IGNORECASE)
    if article_match:
        result["article"] = article_match.group(1).lower()
        work_str = work_str[article_match.end():].strip()
        
    # 6. Check for spelling variants inside headword
    variant_match = re.search(r'^([a-zA-ZäöüÄÖÜß-]+)\/\s*([a-zA-ZäöüÄÖÜß-]+)', work_str)
    if variant_match:
        result["variants"].append(variant_match.group(2))
        work_str = variant_match.group(1) + work_str[variant_match.end():]
        
    # 7. Split word and its inflections/plural
    work_str = work_str.rstrip(";,")
    parts = [p.strip() for p in work_str.split(",") if p.strip()]
    if parts:
        result["headword"] = parts[0]
        if result["article"]:
            if len(parts) > 1:
                result["plural"] = parts[1]
        else:
            if len(parts) > 1:
                result["conjugation"] = parts[1:]
                
    if result["female_form"] and result["headword"] == raw_word:
        fem_headword = result["female_form"]["details"]["headword"]
        if fem_headword:
            result["headword"] = fem_headword
            
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
        word_str = re.sub(r'\s*\d+\.$', '', word_str).strip()
        word_str = clean_word_spaces(word_str)
        example_str = " ".join([w['text'] for w in example_part]).strip()
        
        gap = (t - prev_top) if prev_top is not None else 0
        prev_top = t
        
        is_new_entry = False
        is_new_entry_start = False
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
                
                is_verb_phrase_wrap = word_str.startswith(("gehen/sein", "werden/sein", "haben/sein"))
                is_capitalized_no_article = word_str and word_str[0].isupper() and not starts_with_article and not starts_with_regional and not starts_with_arrow and not is_plural_marker
                is_female_name = False
                if word_str.startswith("die "):
                    fem_word = word_str[4:].split(',')[0].strip()
                    fem_word = re.sub(r'\s*\([A-Z\d\s,.]+\)\s*', ' ', fem_word).strip()
                    fem_word = re.sub(r'\s*(?:[→\u2192]|->).*$', '', fem_word).strip()
                    if fem_word.endswith("in"):
                        is_female_name = True
                is_female_wrap = is_female_name and current_word and "der " in current_word[0].lower()
                
                # Check for structural indicators from previous parsed word
                prev_word_str = current_word[-1].strip() if current_word else ""
                has_open_parenthesis = prev_word_str.count("(") > prev_word_str.count(")")
                
                base_word_str = current_word[0].strip() if current_word else ""
                is_reflexive = bool(re.search(r'\b\(?sich\)?\b', base_word_str.lower())) and base_word_str.lower().strip() != "sich"
                
                starts_with_slash = word_str.strip().startswith(("/", ","))
                has_arrow = any(("→" in w or "->" in w) for w in current_word)
                if is_aux:
                    is_continuation = True
                elif is_verb_phrase_wrap:
                    is_continuation = True
                elif is_female_wrap:
                    is_continuation = True
                elif starts_with_slash:
                    is_continuation = True
                elif is_capitalized_no_article and gap < 13.0 and has_arrow:
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
                    is_article = bool(re.match(r'^((?:der|die|das)(?:\/(?:der|die|das))*)$', prev_word_str.strip(), re.IGNORECASE))
                    is_reference = "→" in prev_word_str and (prev_word_str.endswith("→") or prev_word_str.endswith(":") or prev_word_str.endswith(";"))
                    
                    is_new_entry_start = False
                    if prev_word_str.endswith(" -") or prev_word_str.endswith(", -") or prev_word_str.endswith(",-"):
                        next_word_clean = word_str.strip()
                        starts_with_fem_article = next_word_clean.lower().startswith("die ")
                        first_word = next_word_clean.split()[0] if next_word_clean.split() else ""
                        is_short_suffix = len(first_word) <= 3 or first_word.startswith(("-", "¨-"))
                        if not starts_with_fem_article and not is_short_suffix:
                            is_new_entry_start = True
                            
                    if is_prefix_entry:
                        is_continuation = False
                    elif is_new_entry_start:
                        is_continuation = False
                    elif is_article:
                        is_continuation = True
                    elif is_reference:
                        is_continuation = True
                    elif is_reflexive:
                        is_continuation = True
                    elif prev_word_str.endswith("-") or prev_word_str.endswith(",") or prev_word_str.endswith(":") or prev_word_str.endswith(";"):
                        is_continuation = True
                    else:
                        is_continuation = False
                
                is_new_entry = not is_continuation
                
        if is_new_entry:
            if current_word:
                word_full = clean_word_spaces(join_word_parts(current_word))
                pending_article = None
                for suffix in ["/der", "/die", "/das", "/ der", "/ die", "/ das"]:
                    if word_full.endswith(suffix):
                        pending_article = suffix.split("/")[-1].strip()
                        word_full = word_full[:-len(suffix)].strip()
                        break
                if word_full.endswith("/"):
                    word_full = word_full[:-1].strip()
                word_full = word_full.replace("(pl.)", "(Pl.)").replace("(sg.)", "(Sg.)")
                examples_full = join_example_lines(current_examples)
                if should_skip_word(word_full):
                    pass
                elif len(word_full) > 1 or word_full.lower() not in "abcdefghijklmnopqrstuvwxyzäöüß":
                    entries.append({
                        "id": get_clean_id(word_full),
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
        word_full = clean_word_spaces(join_word_parts(current_word))
        for suffix in ["/der", "/die", "/das", "/ der", "/ die", "/ das", "/"]:
            if word_full.endswith(suffix):
                word_full = word_full[:-len(suffix)].strip()
                break
        word_full = word_full.replace("(pl.)", "(Pl.)").replace("(sg.)", "(Sg.)")
        examples_full = join_example_lines(current_examples)
        if should_skip_word(word_full):
            pass
        elif len(word_full) > 1 or word_full.lower() not in "abcdefghijklmnopqrstuvwxyzäöüß":
            entries.append({
                "id": get_clean_id(word_full),
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
                content_words = [w for w in words if 80 <= w['top'] <= 780 and w['x0'] >= 30]
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

def deep_replace_dashes(obj):
    if isinstance(obj, str):
        obj = obj.replace('\u2013', '-').replace('\u2212', '-')
        obj = re.sub(r',-([a-zA-Z])', r', -\1', obj)
        return obj
    elif isinstance(obj, list):
        return [deep_replace_dashes(item) for item in obj]
    elif isinstance(obj, dict):
        return {deep_replace_dashes(k): deep_replace_dashes(v) for k, v in obj.items()}
    return obj

def post_process_entries(entries, pdf_type):
    # 1. Merge parenthesized combinations in A2
    if pdf_type == "A2":
        merged = []
        i = 0
        while i < len(entries):
            entry = entries[i]
            eid = entry.get("id")
            if eid == "der Bescheid" and i + 1 < len(entries) and entries[i+1].get("id") == "(bekommen/ geben/sagen)":
                next_entry = entries[i+1]
                entry["raw_word"] = "der Bescheid (bekommen / geben / sagen)"
                entry["details"]["verbs"] = ["bekommen", "geben", "sagen"]
                if entry.get("examples") and next_entry.get("examples"):
                    combined_ex = entry["examples"][0] + " " + next_entry["examples"][0]
                    combined_ex = re.sub(r'\s+', ' ', combined_ex).strip()
                    entry["examples"] = [combined_ex] + next_entry["examples"][1:]
                merged.append(entry)
                i += 2
            elif eid == "der Vorschlag" and i + 1 < len(entries) and entries[i+1].get("id") == "(haben/machen)":
                next_entry = entries[i+1]
                entry["raw_word"] = "der Vorschlag, ¨-e (haben / machen)"
                entry["details"]["verbs"] = ["haben", "machen"]
                if entry.get("examples") and next_entry.get("examples"):
                    combined_ex = entry["examples"][0] + " " + next_entry["examples"][0]
                    combined_ex = re.sub(r'\s+', ' ', combined_ex).strip()
                    entry["examples"] = [combined_ex] + next_entry["examples"][1:]
                merged.append(entry)
                i += 2
            elif eid == "weiter" and i + 1 < len(entries) and entries[i+1].get("id") == "(z. B. weitermachen/-helfen)":
                next_entry = entries[i+1]
                entry["raw_word"] = "weiter (z. B. weitermachen / weiterhelfen)"
                entry["details"]["combinations"] = ["weitermachen", "weiterhelfen"]
                entry["examples"] = (entry.get("examples", []) or []) + (next_entry.get("examples", []) or [])
                merged.append(entry)
                i += 2
            else:
                merged.append(entry)
                i += 1
        entries = merged

    entries = [deep_replace_dashes(e) for e in entries]
    processed = []
    for entry in entries:
        eid = entry.get("id")
        raw = entry.get("raw_word", "")
        details = entry.get("details", {})
        
        # Clean up spaces in plural suffixes
        if "plural" in details and isinstance(details["plural"], str):
            details["plural"] = re.sub(r'^-\s+([a-zA-Zäöüß]+)$', r'-\1', details["plural"].strip())
            
        if raw:
            entry["raw_word"] = re.sub(r',\s*-\s+([a-zA-Zäöüß]+)\b', r', -\1', raw)
            raw = entry["raw_word"]
            
        if pdf_type == "A1":
            # 1. der Ausländer
            if eid == "der Ausländer" and "ausländisch" in raw:
                processed.append({
                    "id": "der Ausländer",
                    "raw_word": "der Ausländer, -",
                    "details": {
                        "article": "der",
                        "headword": "Ausländer",
                        "plural": "-"
                    },
                    "examples": ["SInd Sie Ausländerin?"]
                })
                processed.append({
                    "id": "ausländisch",
                    "raw_word": "ausländisch",
                    "details": {
                        "headword": "ausländisch"
                    },
                    "examples": ["Leider habe ich nur ausländisches Geld."]
                })
            # 2. der, die, das
            elif eid == "der" and raw == "der, die, das":
                entry["details"] = {
                    "headword": "der, die, das"
                }
                processed.append(entry)
            # 3. der Partner
            elif eid == "der Partner":
                entry["raw_word"] = "der Partner, - / die Partnerin, -nen"
                entry["details"]["plural"] = "-"
                processed.append(entry)
            # 4. das Wort
            elif eid == "das Wort":
                entry["raw_word"] = "das Wort, ¨-er"
                entry["details"]["plural"] = "¨-er"
                processed.append(entry)
            else:
                processed.append(entry)
                
        elif pdf_type == "A2":
            # 1. Ermäßigung
            if eid == "die Ermäßigung":
                entry["raw_word"] = "die Ermäßigung, -en"
                entry["details"]["plural"] = "-en"
                entry["examples"] = ["Für Schüler, Studenten und Rentner gibt es eine Ermäßigung."]
                processed.append(entry)
            # 2. Fotoapparat
            elif eid == "der Fotoapparat":
                entry["raw_word"] = "der Fotoapparat, -e"
                entry["details"]["plural"] = "-e"
                entry["examples"] = ["Ich möchte mir einen Fotoapparat kaufen."]
                processed.append(entry)
            # 3. Kindergarten
            elif eid == "der Kindergarten":
                entry["raw_word"] = "der Kindergarten, ¨-"
                entry["details"]["plural"] = "¨-"
                entry["examples"] = ["Die kleine Laura geht schon in den Kindergarten."]
                processed.append(entry)
            # 4. Mannschaft
            elif eid == "die Mannschaft":
                entry["raw_word"] = "die Mannschaft, -en"
                entry["details"]["plural"] = "-en"
                entry["examples"] = ["Meine Lieblingsmannschaft hat 1:0 verloren."]
                processed.append(entry)
            # 5. Museum
            elif eid == "das Museum":
                entry["raw_word"] = "das Museum, Museen"
                entry["details"]["plural"] = "Museen"
                processed.append(entry)
            # 6. Supermarkt
            elif eid == "der Supermarkt":
                entry["raw_word"] = "der Supermarkt, ¨-e"
                entry["details"]["plural"] = "¨-e"
                entry["examples"] = ["Ich kaufe oft im Supermarkt ein."]
                processed.append(entry)
            # 7. Wettbewerb
            elif eid == "der Wettbewerb":
                entry["raw_word"] = "der Wettbewerb, -e"
                entry["details"]["plural"] = "-e"
                entry["examples"] = ["Mein Sohn hat bei einem Wettbewerb gewonnen."]
                processed.append(entry)
            # 8. de Rentner
            elif eid == "de Rentner":
                entry["id"] = "der Rentner"
                entry["raw_word"] = "der Rentner, -"
                entry["details"]["article"] = "der"
                entry["details"]["headword"] = "Rentner"
                processed.append(entry)
            # 9. Nouns with trailing slash in plural (Chef, Kollege, Kunde, Schüler, Vermieter)
            elif eid in ["der Chef", "der Kollege", "der Kunde", "der Schüler", "der Vermieter"] and "plural" in details and details["plural"].endswith(("/", "/ ")):
                details["plural"] = details["plural"].rstrip("/ ").strip()
                entry["raw_word"] = re.sub(r'\s*\/\s*\/', ' /', raw)
                processed.append(entry)
            else:
                processed.append(entry)
                
        elif pdf_type == "B1":
            # 1. der Braten
            if eid == "der Braten" and "brauchen" in raw:
                processed.append({
                    "id": "der Braten",
                    "raw_word": "der Braten, -",
                    "details": {
                        "article": "der",
                        "headword": "Braten",
                        "plural": "-"
                    },
                    "examples": ["Nehmen Sie noch etwas Soße zum Braten?"]
                })
                processed.append({
                    "id": "brauchen",
                    "raw_word": "brauchen, braucht, brauchte, hat gebraucht",
                    "details": {
                        "headword": "brauchen",
                        "conjugation": ["braucht", "brauchte", "hat gebraucht"]
                    },
                    "examples": [
                        "Ich brauche ein Auto.",
                        "Brauchst du die Zeitung noch?",
                        "Meine Großmutter ist krank. Sie braucht viel Ruhe.",
                        "Ich habe für die Renovierung eine Woche gebraucht.",
                        "Sie brauchen morgen nicht zu kommen. Ich schaffe das alleine."
                    ]
                })
            # 2. die Diskothek
            elif eid == "die Diskothek":
                entry["raw_word"] = "die Diskothek, -en/die Disko, -s"
                entry["details"] = {
                    "article": "die",
                    "headword": "Diskothek",
                    "plural": "-en/-s",
                    "variants": ["Disko"]
                }
                processed.append(entry)
            # 3. der Speisewagen
            elif eid == "der Speisewagen" and "Spezial" in raw:
                processed.append({
                    "id": "der Speisewagen",
                    "raw_word": "der Speisewagen, -",
                    "details": {
                        "article": "der",
                        "headword": "Speisewagen",
                        "plural": "-"
                    },
                    "examples": ["Wo ist der Speisewagen?"]
                })
                processed.append({
                    "id": "Spezial-",
                    "raw_word": "Spezial-",
                    "details": {
                        "headword": "Spezial-"
                    },
                    "examples": ["Ich brauche eine Spezialpflege für trockenes Haar."]
                })
            # 4. der Wissenschaftler"
            elif eid == "der Wissenschaftler" and "Wissenschaftlerin" in raw:
                entry["raw_word"] = "der Wissenschaftler, - / die Wissenschaftlerin, -nen"
                entry["details"] = {
                    "article": "der",
                    "headword": "Wissenschaftler",
                    "plural": "-",
                    "female_form": {
                        "id": "die Wissenschaftlerin",
                        "raw_word": "die Wissenschaftlerin, -nen",
                        "details": {
                            "article": "die",
                            "headword": "Wissenschaftlerin",
                            "plural": "-nen"
                        }
                    }
                }
                processed.append(entry)
            # 5. die Kursleiter
            elif eid == "die Kursleiter":
                entry["id"] = "die Kursleiterin"
                entry["raw_word"] = "die Kursleiterin, -nen"
                entry["details"]["headword"] = "Kursleiterin"
                processed.append(entry)
            # 6. die Jugendliche
            elif eid == "die Jugendliche":
                entry["raw_word"] = "die Jugendliche, -n"
                entry["details"]["plural"] = "-n"
                processed.append(entry)
            # 7. das Lexikon
            elif eid == "das Lexikon":
                entry["raw_word"] = "das Lexikon, Lexika"
                entry["details"]["plural"] = "Lexika"
                processed.append(entry)
            else:
                processed.append(entry)
        else:
            processed.append(entry)
            
    return processed

def main():
    # A1 list
    a1_entries = parse_pdf_wordlist("../Books/A1_SD1_Wortliste_02.pdf", 9, 27, "A1")
    a1_clean = [clean_entry_dict(e) for e in a1_entries]
    a1_clean = post_process_entries(a1_clean, "A1")
    with open("A1_wortliste.json", "w", encoding="utf-8") as f:
        json.dump(a1_clean, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(a1_clean)} A1 entries to A1_wortliste.json")
    
    # A2 list
    a2_entries = parse_pdf_wordlist("../Books/Goethe-Zertifikat_A2_Wortliste.pdf", 8, 31, "A2")
    a2_clean = [clean_entry_dict(e) for e in a2_entries]
    a2_clean = post_process_entries(a2_clean, "A2")
    with open("A2_wortliste.json", "w", encoding="utf-8") as f:
        json.dump(a2_clean, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(a2_clean)} A2 entries to A2_wortliste.json")
    
    # B1 list
    b1_entries = parse_pdf_wordlist("../Books/Goethe-Zertifikat_B1_Wortliste.pdf", 16, 102, "B1")
    b1_clean = [clean_entry_dict(e) for e in b1_entries]
    b1_clean = post_process_entries(b1_clean, "B1")
    with open("B1_wortliste.json", "w", encoding="utf-8") as f:
        json.dump(b1_clean, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(b1_clean)} B1 entries to B1_wortliste.json")

if __name__ == "__main__":
    main()
