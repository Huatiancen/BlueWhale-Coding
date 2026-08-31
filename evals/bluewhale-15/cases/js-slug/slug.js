function slugify(value) {
  return value.toLowerCase().trim().replace(/\s/g, '-');
}

module.exports = { slugify };
