import codecs
from ruamel import yaml

with codecs.open('Data/goethe_word_list.yaml', 'r', 'utf-8') as f:
    words = yaml.load(f)

lists = {}

for word in words:
    if word['Examples'][0].startswith('example'):
        continue
    lists[word['Level']] = lists.get(word['Level'], [])
    lists[word['Level']] += [word['Id']]

output = [{'Id':k,'Words':v} for k,v in lists.items()]

with codecs.open('Data/goethe_lists.yaml', 'w', 'utf-8') as f:
    yaml.dump(output, f, allow_unicode=True, default_flow_style=False)
