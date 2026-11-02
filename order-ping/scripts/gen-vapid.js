// يولّد مفاتيح VAPID ويحفظها في ملف .env (مرة وحدة فقط)
const fs = require('fs');
const path = require('path');
const webpush = require('web-push');

const envPath = path.join(__dirname, '..', '.env');
if (fs.existsSync(envPath) && fs.readFileSync(envPath, 'utf8').includes('VAPID_PUBLIC_KEY')) {
  console.log('.env فيه مفاتيح من قبل، ما تغير شي.');
  process.exit(0);
}

const keys = webpush.generateVAPIDKeys();
const content = [
  `VAPID_PUBLIC_KEY=${keys.publicKey}`,
  `VAPID_PRIVATE_KEY=${keys.privateKey}`,
  'VAPID_SUBJECT=mailto:you@example.com',
  'CASHIER_PIN=1234',
  'PORT=3000',
  '',
].join('\n');

fs.appendFileSync(envPath, content);
console.log('تم إنشاء .env بالمفاتيح.');
