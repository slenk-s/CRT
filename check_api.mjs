import { spawn } from 'node:child_process';
import http from 'node:http';

function get(path){ return new Promise((resolve,reject)=>{ http.get('http://127.0.0.1:8001'+path,res=>{let d='';res.on('data',c=>d+=c);res.on('end',()=>resolve({status:res.statusCode,body:d}));}).on('error',reject); }); }
const me = await get('/api/auth/me');
console.log('me', me.status, me.body.slice(0,120));
