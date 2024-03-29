ARG BASE=ubuntu:latest

FROM ${BASE} AS base_image

FROM base_image AS build

RUN apt-get update && apt-get install -y curl supervisor build-essential checkinstall zlib1g-dev libpcre3-dev ffmpeg libssl-dev && rm -rf /var/lib/apt/lists/*;
RUN mkdir nginx nginx-vod-module

ARG NGINX_VERSION=1.23.4
ARG VOD_MODULE_VERSION=6c305a78b7ab6e4312279bea5c45741bb54a713b

WORKDIR /home

RUN curl -sL https://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz | tar -C /nginx --strip 1 -xz
RUN curl -sL https://github.com/kaltura/nginx-vod-module/archive/${VOD_MODULE_VERSION}.tar.gz | tar -C /nginx-vod-module --strip 1 -xz

WORKDIR /nginx
RUN ./configure --prefix=/usr/local/nginx \
	--add-module=../nginx-vod-module \
	--with-http_ssl_module \
	--with-file-aio \
	--with-threads \
	--with-cc-opt="-O3"
RUN make
RUN make install
RUN rm -rf /usr/local/nginx/html /usr/local/nginx/conf/*.default

FROM base_image
RUN apt-get update && apt-get install --no-install-recommends -y ca-certificates openssl libpcre3 zlib1g ffmpeg && rm -rf /var/lib/apt/lists/*;
COPY --from=build /usr/local/nginx /usr/local/nginx
ENTRYPOINT ["/usr/local/nginx/sbin/nginx"]
CMD ["-g", "daemon off;"]
