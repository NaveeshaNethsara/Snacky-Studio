import { defineConfig } from '@playwright/test';
import { resolve } from 'node:path';
export default defineConfig({
 testDir:'./e2e', fullyParallel:false, workers:1, timeout:60000,
 use:{baseURL:'http://127.0.0.1:8124',channel:process.env.SNACKY_BROWSER_CHANNEL || undefined,headless:true,acceptDownloads:true,trace:'retain-on-failure'},
 webServer:{command:process.env.SNACKY_TEST_PYTHON ? `"${process.env.SNACKY_TEST_PYTHON}" -m tests.ui_preview` : `"${resolve('../.venv/Scripts/python.exe')}" -m tests.ui_preview`,cwd:'..',url:'http://127.0.0.1:8124/api/health',reuseExistingServer:false,timeout:60000},
});
