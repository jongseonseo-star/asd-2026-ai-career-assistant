FROM nginx:1.27-alpine

ENV STUDENT2_FRONTEND_URL=http://student-2-frontend:8082 \
    STUDENT3_FRONTEND_URL=http://student-3-frontend:8083 \
    STUDENT4_FRONTEND_URL=http://student-4-frontend:8404 \
    STUDENT2_PUBLIC_PORT=8082 \
    STUDENT3_PUBLIC_PORT=8303 \
    STUDENT4_PUBLIC_PORT=8404

COPY index.html /usr/share/nginx/html/index.html
COPY assets/styles.css /usr/share/nginx/html/assets/styles.css
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 80 8082 8303 8404
