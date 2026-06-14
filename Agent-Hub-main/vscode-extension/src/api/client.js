"use strict";

async function requestJson(extensionApi, method, pathname, body) {
  return extensionApi.requestJson(method, pathname, body);
}

module.exports = { requestJson };
