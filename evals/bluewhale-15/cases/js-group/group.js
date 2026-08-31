function groupBy(items, key) {
  const groups = {};
  for (const item of items) {
    groups[item[key]] = [item];
  }
  return groups;
}

module.exports = { groupBy };
