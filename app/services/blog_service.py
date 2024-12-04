from app.models import Article, Category, Tag, Comment, ViewHistory, File, User
from sqlalchemy import func
from datetime import datetime, timedelta
from app.utils.cache_manager import cache_manager
from app import db
import os
import hashlib
from flask import current_app
import random


class BlogService:
    # 定义缓存过期时间常量
    CACHE_TIMES = {
        'INDEX': 3600,        # 首页缓存1小时
        'ARTICLE': 43200,     # 文章详情缓存12小时
        'HOT_TODAY': 600,     # 今日热门缓存10分钟
        'HOT_WEEK': 1800,     # 本周热门缓存30分钟
        'RANDOM': 300,        # 随机推荐缓存5分钟
        'TAGS': 3600,         # 标签缓存1小时
        'COMMENTS': 300,      # 评论缓存5分钟
        'SEARCH': 1800,       # 搜索结果缓存30分钟
        'CATEGORY': 3600      # 分类缓存1小时
    }

    @staticmethod
    def get_index_articles(page=1, category_id=None):
        """获取首页文章列表"""
        def query_articles():
            with db.session.no_autoflush:
                query = Article.query.options(
                    db.joinedload(Article.author),
                    db.joinedload(Article.category),
                    db.joinedload(Article.tags)
                )
                return query.order_by(Article.id.desc(), Article.created_at.desc())\
                           .paginate(page=page, per_page=10, error_out=False)
                       
        return cache_manager.get(f'index:articles:{page}:{category_id}', 
                               query_articles, 
                               ttl=BlogService.CACHE_TIMES['INDEX'])

    @staticmethod
    def get_category_articles(category_id, page=1):
        """获取分类下的文章列表（包含子分类的文章）"""
        def query_articles():
            try:
                # 获取当前分类
                category = Category.query.get_or_404(category_id)
                
                # 获取所有子分类ID（包括当前分类）
                category_ids = [category_id]
                for child in category.get_descendants():
                    category_ids.append(child.id)
                
                # 构建查询
                query = Article.query\
                    .options(
                        db.joinedload(Article.author),
                        db.joinedload(Article.category),
                        db.joinedload(Article.tags)
                    )\
                    .filter(Article.category_id.in_(category_ids))\
                    .order_by(Article.id.desc(), Article.created_at.desc())
                
                # 分页
                pagination = query.paginate(page=page, per_page=10, error_out=False)
                
                # 返回与原有控制器完全一致的格式
                return {
                    'pagination': pagination,
                    'current_category': category
                }
                
            except Exception as e:
                current_app.logger.error(f"Get category articles error: {str(e)}")
                return None

        # 使用缓存
        return cache_manager.get(
            f'category:{category_id}:page:{page}', 
            query_articles,
            ttl=BlogService.CACHE_TIMES['CATEGORY']
        )

    @staticmethod
    def get_article_detail(article_id):
        """获取文章详情"""
        def query_article():
            return Article.query.options(
                db.joinedload(Article.author),
                db.joinedload(Article.tags),
                db.joinedload(Article.category),
                db.joinedload(Article.comments).joinedload(Comment.user)
            ).get_or_404(article_id)
            
        return cache_manager.get(f'article:{article_id}', 
                               query_article,
                               ttl=BlogService.CACHE_TIMES['ARTICLE'])

    @staticmethod
    def get_hot_articles_today():
        """获取今日热门文章"""
        def query_hot():
            today = datetime.now().date()
            views_subquery = db.session.query(
                ViewHistory.article_id,
                func.count(ViewHistory.id).label('views')
            ).filter(
                func.date(ViewHistory.viewed_at) == today
            ).group_by(ViewHistory.article_id)\
             .subquery()
            
            return db.session.query(Article, views_subquery.c.views)\
                .join(views_subquery, Article.id == views_subquery.c.article_id)\
                .options(db.joinedload(Article.author))\
                .order_by(views_subquery.c.views.desc())\
                .limit(5)\
                .all()
                
        return cache_manager.get('hot_articles:today', 
                               query_hot,
                               ttl=BlogService.CACHE_TIMES['HOT_TODAY'])

    @staticmethod
    def get_hot_articles_week():
        """获取本周热门文章"""
        def query_hot():
            today = datetime.now().date()
            week_start = today - timedelta(days=today.weekday())
            views_subquery = db.session.query(
                ViewHistory.article_id,
                func.count(ViewHistory.id).label('views')
            ).filter(
                func.date(ViewHistory.viewed_at) >= week_start
            ).group_by(ViewHistory.article_id)\
             .subquery()
            
            return db.session.query(Article, views_subquery.c.views)\
                .join(views_subquery, Article.id == views_subquery.c.article_id)\
                .options(db.joinedload(Article.author))\
                .order_by(views_subquery.c.views.desc())\
                .limit(5)\
                .all()
                
        return cache_manager.get('hot_articles:week', 
                               query_hot,
                               ttl=BlogService.CACHE_TIMES['HOT_WEEK'])

    @staticmethod
    def get_random_articles():
        """获取随机推荐文章"""
        def query_random():
            count = Article.query.count()
            if count < 5:
                return Article.query.all()
            ids = random.sample(range(1, count + 1), min(5, count))
            return Article.query\
                .options(db.joinedload(Article.author))\
                .filter(Article.id.in_(ids))\
                .all()
                
        return cache_manager.get('random_articles', 
                               query_random,
                               ttl=BlogService.CACHE_TIMES['RANDOM'])

    @staticmethod
    def get_random_tags():
        """获取随机标签"""
        def query_tags():
            count = Tag.query.count()
            if count < 10:
                return Tag.query.all()
            ids = random.sample(range(1, count + 1), min(10, count))
            return Tag.query.filter(Tag.id.in_(ids)).all()
                
        return cache_manager.get('random_tags', 
                               query_tags,
                               ttl=BlogService.CACHE_TIMES['TAGS'])

    @staticmethod
    def get_latest_comments():
        """获取最新评论"""
        def query_comments():
            return db.session.query(Comment, User, Article)\
                .join(User, Comment.user_id == User.id)\
                .join(Article, Comment.article_id == Article.id)\
                .order_by(Comment.created_at.desc())\
                .limit(10)\
                .all()
                
        return cache_manager.get('latest_comments', 
                               query_comments,
                               ttl=BlogService.CACHE_TIMES['COMMENTS'])
    
    @staticmethod
    def record_view(user_id, article_id):
        """记录文章浏览"""
        view = ViewHistory(user_id=user_id, article_id=article_id)
        db.session.add(view)
        
        # 更新浏览次数
        article = Article.query.get(article_id)
        article.view_count += 1
        db.session.commit()
    
    @staticmethod
    def search_articles(query, page=1, selected_tags=None, sort='recent'):
        """搜索文章"""
        def do_search():
            # 构建基础查询
            base_query = Article.query.options(
                db.joinedload(Article.author),
                db.joinedload(Article.category)
            )
            
            # 搜索标题
            base_query = base_query.filter(Article.title.ilike(f'%{query}%'))
            
            # 标签过滤
            if selected_tags:
                tag_subquery = db.session.query(Article.id)\
                    .join(Article.tags)\
                    .filter(Tag.name.in_(selected_tags))\
                    .group_by(Article.id)\
                    .having(db.func.count(Tag.id) == len(selected_tags))\
                    .subquery()
                base_query = base_query.filter(Article.id.in_(tag_subquery))
            
            # 排序处理
            if sort == 'views':
                base_query = base_query.order_by(Article.view_count.desc())
            elif sort == 'comments':
                comment_counts = db.session.query(
                    Article.id,
                    db.func.count(Comment.id).label('comment_count')
                ).outerjoin(Comment)\
                 .group_by(Article.id)\
                 .subquery()
                
                base_query = base_query.outerjoin(
                    comment_counts,
                    Article.id == comment_counts.c.id
                ).order_by(db.desc(comment_counts.c.comment_count))
            else:  # recent
                base_query = base_query.order_by(Article.created_at.desc())
            
            return base_query.paginate(page=page, per_page=10, error_out=False)
            
        # 生成缓存键，包含所有搜索参数
        cache_key = f'search:{query}:tags:{"-".join(sorted(selected_tags or []))}:sort:{sort}:page:{page}'
        return cache_manager.get(cache_key, do_search, ttl=BlogService.CACHE_TIMES['SEARCH'])

    @staticmethod
    def get_tag_articles(tag_id, page=1):
        """获取标签下的文章"""
        def query_tag_articles():
            return Article.query.options(
                db.joinedload(Article.author),
                db.joinedload(Article.category)
            ).filter(Article.tags.any(Tag.id == tag_id))\
             .order_by(Article.created_at.desc())\
             .paginate(page=page, per_page=10, error_out=False)
            
        return cache_manager.get(f'tag:{tag_id}:articles:{page}', query_tag_articles)
    
    @staticmethod
    def get_tag_info(tag_id):
        """获取标签信息"""
        return cache_manager.get(
            f'tag:{tag_id}',
            lambda: Tag.query.get_or_404(tag_id)
        )
    
    @staticmethod
    def add_comment(article_id, user_id, content):
        """添加评论"""
        try:
            comment = Comment(
                content=content,
                article_id=article_id,
                user_id=user_id
            )
            db.session.add(comment)
            db.session.commit()
            
            # 清除相关缓存
            cache_manager.delete(f'article:{article_id}')  # 文章详情缓存
            cache_manager.delete('latest_comments')        # 最新评论缓存
            
            return True, '评论发表成功'
        except Exception as e:
            db.session.rollback()
            return False, f'评论发表失败: {str(e)}'
    
    @staticmethod
    def delete_comment(comment_id, user_id, is_admin=False):
        """删除评论"""
        try:
            comment = Comment.query.get_or_404(comment_id)
            if comment.user_id != user_id and not is_admin:
                return False, '没有权限删除此评论'
            
            article_id = comment.article_id
            db.session.delete(comment)
            db.session.commit()
            
            # 清除相关缓存
            cache_manager.delete(f'article:{article_id}')  # 文章详情缓存
            cache_manager.delete('latest_comments')        # 最新评论缓存
            
            return True, '评论已删除'
        except Exception as e:
            db.session.rollback()
            return False, f'删除失败: {str(e)}'
    
    @staticmethod
    def edit_article(article_id, form_data, user_id, is_admin=False):
        """编辑文章"""
        try:
            if article_id:
                article = Article.query.get_or_404(article_id)
                if not is_admin and article.author_id != user_id:
                    return False, '没有权限编辑此文章', None
            else:
                article = Article(author_id=user_id)
                db.session.add(article)
            
            # 更新基本信息
            article.title = form_data.get('title')
            article.content = form_data.get('content')
            article.category_id = form_data.get('category', type=int)
            
            # 处理标签
            tags = []
            tag_names = form_data.getlist('tags')
            for name in tag_names:
                name = name.strip()
                if name:
                    tag = Tag.query.filter_by(name=name).first()
                    if not tag:
                        tag = Tag(name=name)
                        db.session.add(tag)
                    tags.append(tag)
            
            # 使用新的事务处理标签关联
            with db.session.begin_nested():
                # 清除旧的标签关联
                if article_id:
                    article.tags = []
                    db.session.flush()
                # 设置新的标签
                article.tags = tags
            
            db.session.commit()
            
            # 清除缓存
            cache_manager.delete_many([
                'index:articles:*',
                f'article:{article.id}',
                'tag_*',
                'category:*'
            ])
            
            return True, '保存成功', article
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Edit article error: {str(e)}")
            return False, f'保存失败: {str(e)}', None
    
    @staticmethod
    def get_tag_suggestions(query):
        """获取标签建议"""
        def query_tags():
            return Tag.query.filter(
                Tag.name.ilike(f'%{query}%')
            ).order_by(Tag.article_count.desc()).limit(10).all()
            
        return cache_manager.get(f'tag_suggestions:{query}', query_tags)
    
    @staticmethod
    def upload_image(file, user_id):
        """上传图片"""
        try:
            # 生成文件内容的 MD5 哈希值
            file_content = file.read()
            file_hash = hashlib.md5(file_content).hexdigest()
            file.seek(0)  # 重置文件指针
            
            # 检查是否存在相同的文件
            existing_file = File.query.filter_by(md5=file_hash).first()
            if existing_file:
                return True, existing_file.file_path
            
            # 生成日期路径和文件名
            date_path = datetime.now().strftime('%Y%m%d')
            file_ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{file_hash}.{file_ext}"
            
            # 创建目录
            upload_folder = os.path.join(current_app.static_folder, 'uploads', 'images', date_path)
            os.makedirs(upload_folder, exist_ok=True)
            
            # 保存件
            file_path = os.path.join(upload_folder, filename)
            file.save(file_path)
            
            # 使用相对路径
            relative_path = f'/static/uploads/images/{date_path}/{filename}'
            
            # 保存文件信息到数据库
            db_file = File(
                filename=filename,
                original_filename=file.filename,
                file_path=relative_path,
                file_type='images/'+file_ext,
                file_size=os.path.getsize(file_path),
                md5=file_hash,
                uploader_id=user_id
            )
            db.session.add(db_file)
            db.session.commit()
            
            return True, relative_path
            
        except Exception as e:
            db.session.rollback()
            if os.path.exists(file_path):
                os.remove(file_path)
            return False, str(e)
    
    @staticmethod
    def delete_article(article_id, user_id, is_admin=False):
        """删除文章"""
        try:
            article = Article.query.get_or_404(article_id)
            
            # 权限检查
            if article.author_id != user_id and not is_admin:
                return False, '没有权限删除此文章'
            
            # 删除文章
            db.session.delete(article)
            db.session.commit()
            
            # 清除相关缓存
            BlogService.clear_article_related_cache(article_id)
            # 清除用户文章列表缓存
            cache_manager.delete(f'user:{user_id}:articles:*')
            
            return True, '文章已删除'
            
        except Exception as e:
            db.session.rollback()
            return False, f'删除失败: {str(e)}'
    
    @staticmethod
    def clear_article_related_cache(article_id):
        """清除文章相关的所有缓存"""
        # 使用列表管理需要清除的缓存键模式
        cache_patterns = [
            f'article:{article_id}',    # 文章详情缓存
            'index:articles:*',         # 首页文章列表缓存
            'category:*',               # 分类文章列表缓存
            'hot_articles:*',           # 热门文章缓存
            'random_articles',          # 随机文章缓存
            'search:*',                 # 搜索结果缓存
            'tag:*',                    # 标签相关缓存
            'search_suggestions:*',     # 搜索建议缓存
            'search_tags:*'             # 搜索标签缓存
        ]
        
        # 批量清除缓存
        for pattern in cache_patterns:
            cache_manager.delete(pattern)
    
    @staticmethod
    def get_search_suggestions(query):
        """获取搜索建议"""
        def query_suggestions():
            return Article.query.with_entities(Article.title)\
                .filter(Article.title.ilike(f'%{query}%'))\
                .order_by(Article.view_count.desc())\
                .limit(5)\
                .all()
            
        return cache_manager.get(f'search_suggestions:{query}', 
                               query_suggestions,
                               ttl=BlogService.CACHE_TIMES['SEARCH'])
    
    @staticmethod
    def get_search_tags(query):
        """获取搜索相关标签"""
        def query_tags():
            return Tag.query.join(Article.tags)\
                .filter(Article.title.ilike(f'%{query}%'))\
                .distinct()\
                .order_by(Tag.article_count.desc())\
                .all()
                
        return cache_manager.get(f'search_tags:{query}', 
                               query_tags,
                               ttl=BlogService.CACHE_TIMES['SEARCH'])
    
    @staticmethod
    def warmup_cache():
        """预热常用缓存"""
        warmup_keys = {
            'index:articles:1': lambda: BlogService.get_index_articles(1),
            'hot_articles:today': lambda: BlogService.get_hot_articles_today(),
            'hot_articles:week': lambda: BlogService.get_hot_articles_week(),
            'random_articles': lambda: BlogService.get_random_articles(),
            'random_tags': lambda: BlogService.get_random_tags(),
            'latest_comments': lambda: BlogService.get_latest_comments()
        }
        cache_manager.warmup(warmup_keys)

