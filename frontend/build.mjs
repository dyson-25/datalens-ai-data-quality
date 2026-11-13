import { mkdir, copyFile } from 'node:fs/promises';
await mkdir(new URL('./vendor/', import.meta.url), { recursive: true });
await copyFile(new URL('../node_modules/echarts/dist/echarts.min.js', import.meta.url), new URL('./vendor/echarts.min.js', import.meta.url));
await copyFile(new URL('../node_modules/echarts/LICENSE', import.meta.url), new URL('./vendor/ECHARTS-LICENSE.txt', import.meta.url));
console.log('Built local Tailwind and ECharts assets.');
