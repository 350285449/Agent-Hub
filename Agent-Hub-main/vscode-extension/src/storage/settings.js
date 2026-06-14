"use strict";

function setting(config, key, fallback) {
  return config && Object.prototype.hasOwnProperty.call(config, key) ? config[key] : fallback;
}

module.exports = { setting };
