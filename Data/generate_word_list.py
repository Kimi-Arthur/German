import codecs
from ruamel import yaml

with codecs.open('goethe_word_list.yaml', 'r', 'utf-8') as f:
    words = yaml.load(f)

lists = {}

for word in words:
    lists[word['Level']] = lists.get(word['Level'], [])
    lists[word['Level']] += [word['Word']]

output = [{'Id':k,'Words':v} for k,v in lists.items()]

with codecs.open('word_lists.yaml', 'w', 'utf-8') as f:
    yaml.dump(output, f)
