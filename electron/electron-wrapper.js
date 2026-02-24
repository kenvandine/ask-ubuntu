#!/usr/bin/env node

// Wrapper script to handle model arguments for Electron app
const { spawn } = require('child_process');
const path = require('path');

// Get the directory of this script
const scriptDir = __dirname;
const repoRoot = path.join(scriptDir, '..');

// Extract model argument from command line
const modelArg = process.argv.find(arg => arg.startsWith('--model='));
const modelValue = modelArg ? modelArg.split('=')[1] : null;

// Build the command to start Electron
const electronArgs = [
  path.join(scriptDir, 'main.js'),
  '--no-sandbox'
];

// If model is provided, pass it to the server via environment variable
const env = { ...process.env };
if (modelValue) {
  env.ASK_UBUNTU_MODEL = modelValue;
}

// Spawn Electron process
const electronProcess = spawn('electron', electronArgs, {
  cwd: scriptDir,
  env: env,
  stdio: 'inherit'
});

electronProcess.on('close', (code) => {
  process.exit(code);
});

electronProcess.on('error', (err) => {
  console.error('Failed to start Electron:', err);
  process.exit(1);
});