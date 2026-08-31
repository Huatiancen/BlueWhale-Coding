async function retry(operation, retries) {
  return operation();
}

module.exports = { retry };
